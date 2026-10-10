// annotate page code, part 9 of 9 (see script.js): the poll delta, the
// document refresh and reconcile — and, last, the boot.

function onPollDelta(data, lastVersions) {
  const watcherDead = typeof data.watcher_age_s === "number"
    && data.watcher_age_s > WATCHER_DEAD_AFTER_S;
  setWatcherDead(watcherDead);
  // A dead watcher means no ack is ever coming — don't keep the page
  // locked on its behalf.
  const busyNow = !!(data.busy && !watcherDead);
  if (busyNow && !wasBusy) {
    // A new round just started: last round's verdict is stale now.
    clearChangeAttribution();
    roundBaseVersions = lastVersions ? { ...lastVersions } : null;
    windowHadRound = hasPendingRound();
  } else if (!busyNow && wasBusy) {
    // Only a round earns a change bar. A general comment or a choice pick
    // also opens and closes a busy window, and the blocks Claude rewrites
    // answering one of those were not asked for by any round — attributing
    // them against the last round's block ids is how the bar started lying.
    let changed = [];
    if (windowHadRound) {
      changed = computeChangeSet(roundBaseVersions, data.blocks);
      // The bar has now finished consuming the submitted set: this line is
      // the LAST read of it (applyChangeSet only carries the already-derived
      // `bySweep` flag). Cleared here rather than in clearRound() because
      // that runs on the ack, which can land a poll or more before busy goes
      // false when a second event is still in flight — clearing there would
      // hand computeChangeSet an empty asked-set and label the user's own
      // marked blocks "sweep".
      window.AnnotateSubunits?.clearSubmittedBlockIds?.();
    }
    windowHadRound = false;
    roundBaseVersions = null;
    if (changed.length) pendingChangeSet = changed;
    // Nothing to attribute: the round is answered, so the reader's saves
    // during it are settled too.
    else pageWrites.clear();
  }
  wasBusy = busyNow;
  setBusy(busyNow);
  setAttachedPill(data.attached);
  // 1. Clear spinners for comments Claude finished processing.
  handleConsumedEvents(data.consumed_events);
  if (window.AnnotateSubunits) window.AnnotateSubunits.onPoll(data);
  // 2. Reconcile the DOM against the full document.
  refreshDocument();
}

// /raw carries everything (per-block markdown/svg + version + glossary), so
// one fetch covers structure, content, and glossary in a single pass.
//
// One at a time, and one more at most. Every delta and every lock change
// asks for a refresh; a fetch already in flight answers none that arrive
// after it started, so those collapse into a single follow-up, and two
// fetches can no longer land out of order and reconcile an older document
// over a newer one.
let refreshing = false;
let refreshAgain = false;
function refreshDocument() {
  if (refreshing) { refreshAgain = true; return; }
  refreshing = true;
  refreshOnce()
    .catch(() => { /* swallow — next tick retries */ })
    .then(() => {
      refreshing = false;
      if (refreshAgain) { refreshAgain = false; refreshDocument(); }
    });
}

// A rewrite should land coloured, not plain and then coloured a moment
// later. So a refresh waits for the grammars its document names, but never
// long: past this it renders plain, and repaintCode colours it when they
// arrive.
const PREPARE_WAIT_MS = 1500;
function codeReadyFor(doc) {
  if (!window.CodePaint || !CodePaint.prepare) return Promise.resolve();
  return Promise.race([
    CodePaint.prepare(doc),
    new Promise((resolve) => setTimeout(resolve, PREPARE_WAIT_MS)),
  ]);
}

async function refreshOnce() {
  const r = await fetch(BASE + "raw", { cache: "no-store" });
  const doc = r.ok ? await r.json() : null;
  if (!doc) return;
  await codeReadyFor(doc);
  if ((doc.response_id || "") !== (document.body.dataset.responseId || "")) {
    startNewResponse(doc);
  }
  reconcile(doc);
  syncGlossary(doc);
  // Attribution lands only after reconcile: the chips hang off the
  // refreshed sections (a kind flip rebuilds the whole card) and the
  // diff needs this doc's post-round markdown.
  if (pendingChangeSet) {
    const byId = new Map((doc.blocks || []).map(b => [b.id, b]));
    const changed = pendingChangeSet.filter((c) => {
      const w = pageWrites.get(c.blockId);
      return !w || !sameAsWritten(w, byId.get(c.blockId));
    });
    pendingChangeSet = null;
    pageWrites.clear();
    // Not chained into the outer .catch: it is a floating promise, so
    // without this a throw becomes an unhandled rejection. The bar and
    // the panes that did render stay put.
    applyChangeSet(changed, doc)
      .catch(e => console.warn("change attribution failed", e));
  }
}

// Claude pushed a new response into this session. The page read the
// response id once, at load, and kept keying marks and drafts by it — so the
// first response's marks sat in the dock over the second response's
// same-numbered sections, and Submit would have applied them there.
function startNewResponse(doc) {
  const rid = doc.response_id || "";
  document.body.dataset.responseId = rid;
  const hdr = document.getElementById("hdr-respid");
  if (hdr) hdr.textContent = rid;
  if (doc.title) {
    document.title = doc.title;
    const t = document.getElementById("hdr-title");
    if (t) t.textContent = doc.title;
  }
  try { localStorage.removeItem(STORAGE_KEY); } catch {}
  STORAGE_KEY = `annotate.drafts.${rid}`;
  annotations = loadDrafts();
  renderComments();
  window.AnnotateSubunits?.resetForResponse(rid);
}

function syncGlossary(doc) {
  if (!window.AnnotateGlossary) return;
  const prev = JSON.stringify(window.AnnotateGlossary._lastGlossary || []);
  const next = JSON.stringify(doc.glossary || []);
  if (next !== prev) {
    window.AnnotateGlossary.setGlossary(doc.glossary || []);
    window.AnnotateGlossary._lastGlossary = doc.glossary || [];
    window.AnnotateGlossary.refreshAll();
    // Redecoration rebuilds text nodes: rebuild the span ranges from text.
    window.AnnotateSubunits?.paintSpans?.();
  }
}

// Bring the rendered block list in line with the server document: insert
// newly-added blocks (in order), drop removed ones, and refresh blocks whose
// version bumped. Surgical on purpose — it touches comment wrappers only for
// removed blocks, so a draft the user is mid-typing on an unchanged block is
// never rebuilt out from under them.
function reconcile(doc) {
  if (!proseEl) return;
  const serverBlocks = doc.blocks || [];
  const serverIds = new Set(serverBlocks.map(b => b.id));
  refreshPageState();

  // Remove sections (and their inline-comments wrapper) for deleted blocks,
  // clearing any running updating-timer so it can't leak.
  let orphanedDraft = false;
  let removedAny = false;
  proseEl.querySelectorAll("section.block").forEach(section => {
    if (!serverIds.has(section.dataset.blockId)) {
      // Open in the editor: the reader's text is in there and nowhere else.
      // The section stays until they have copied it and closed.
      if (section.dataset.editing != null) {
        if (!section._removed) {
          section._removed = true;
          window.AnnotateEdit?.removed?.(section.dataset.blockId);
        }
        return;
      }
      clearUpdatingOverlay(section);
      untrackMockupFrames(section);
      const ic = section.nextElementSibling;
      if (ic && ic.classList.contains("inline-comments")) ic.remove();
      section.remove();
      removedAny = true;
      for (const a of Object.values(annotations)) {
        if (a.block_id !== section.dataset.blockId) continue;
        orphanedDraft = true;
        // An open card's typed words go where a pinned comment's do.
        if ((a.comment || "").trim()) {
          document.dispatchEvent(new CustomEvent("annotate:orphan-comment",
            { detail: { text: a.comment.trim(), quote: a.selected_text || "" } }));
        }
      }
    }
  });
  // Pending round marks on a removed block are pruned now, not at the next
  // Submit: the dock must stop listing them, and a comment among them moves
  // to the general box while the reader can still see it happen.
  if (removedAny) window.AnnotateSubunits?.renderDock();
  // The card went with its block, but the draft behind it did not, and one
  // open draft is the page's "someone is editing" lock: every other comment
  // icon refused to open until a reload. renderComments prunes it. Only
  // then, because it rebuilds every card, which would take the caret from a
  // reader typing in some other one.
  if (orphanedDraft) renderComments();

  // Walk server order; insert missing blocks at the right spot, refresh
  // version-bumped ones. `anchor` trails the last placed section (past its
  // comment wrapper) so an inserted block lands in document order.
  let anchor = null;
  for (const blk of serverBlocks) {
    let section = proseEl.querySelector(`section.block[data-block-id="${cssEsc(blk.id)}"]`);
    if (!section) {
      section = createBlockSection(blk);
      if (anchor) anchor.insertAdjacentElement("afterend", section);
      else proseEl.insertBefore(section, proseEl.firstChild);
    } else {
      const domVer = parseInt(section.dataset.version || "1", 10);
      const srvVer = parseInt(blk.version, 10) || 1;
      if (srvVer > domVer) section = updateBlockContent(section, blk, srvVer);
    }
    const ic = section.nextElementSibling;
    anchor = (ic && ic.classList.contains("inline-comments")) ? ic : section;
  }

  // Sections inserted above were built detached; paint their block marks.
  window.AnnotateSubunits?.repaintBlocks();
  applyEngagedStyling();
  document.dispatchEvent(new CustomEvent("annotate:rendered"));
}

// Where the caret is inside a card that is about to be rebuilt. A rebuilt
// choice block dropped focus to <body>, so the reader's next keystrokes
// went nowhere, or into the page's own letter shortcuts.
function focusWithin(section) {
  const el = document.activeElement;
  if (!el || !section.contains(el)) return null;
  if (el.classList.contains("choice-note")) {
    return { note: true, start: el.selectionStart, end: el.selectionEnd };
  }
  const opt = el.closest(".choice-option");
  if (opt) {
    const i = [...section.querySelectorAll(".choice-option")].indexOf(opt);
    return { option: i };
  }
  return null;
}

function restoreFocus(section, focus) {
  if (!focus) return;
  if (focus.note) {
    const note = section.querySelector(".choice-note");
    if (!note) return;
    note.focus({ preventScroll: true });
    const end = note.value.length;
    note.setSelectionRange(Math.min(focus.start, end), Math.min(focus.end, end));
  } else if (typeof focus.option === "number") {
    const opts = section.querySelectorAll(".choice-option");
    const el = opts[Math.min(focus.option, opts.length - 1)];
    if (el) el.focus({ preventScroll: true });
  }
}

// Refresh one block's content in place. Returns the section now in the DOM
// (a fresh node when the block's kind flipped). Clears the updating overlay
// as a fallback for the case where the refreshed block IS the commented one.
function updateBlockContent(section, blk, srvVer) {
  // A section open in the editor is the reader's until they close it: a
  // rewrite landing now would destroy the editor and their words. The
  // newest server block waits on the section, and edit.js applies it on
  // close when it is newer than what the reader saved.
  if (section.dataset.editing != null) {
    const v = parseInt(blk.version ?? srvVer, 10) || 0;
    const had = section._pendingBlock;
    if (!had || v >= had.version) section._pendingBlock = { block: blk, version: v };
    return section;
  }
  const newKind = blk.kind || "markdown";
  const oldKind = section.dataset.kind || "markdown";
  // A kind flip (markdown↔sequence/diagram/choice) needs a fresh section:
  // the diagram click listener and hover wiring are bound at creation, so an
  // in-place innerHTML swap would leave them inconsistent with the new kind.
  // choice, mockup and explain are always rebuilt: none has an in-place
  // repaint below, and the markdown fallback would render the `markdown`
  // field they do not have, leaving the card blank.
  if (newKind !== oldKind || newKind === "choice" || newKind === "mockup"
      || newKind === "explain") {
    const focus = focusWithin(section);
    const fresh = createBlockSection(blk);
    clearUpdatingOverlay(section);
    untrackMockupFrames(section);
    section.replaceWith(fresh);
    restoreFocus(fresh, focus);
    return fresh;
  }
  const content = section.querySelector(".block-content");
  if (content) {
    if (newKind === "sequence") {
      // Both halves again. The pairing listeners live on .block-content,
      // which survives this swap.
      paintSequence(content, blk);
    } else if (newKind === "flowchart") {
      // Without this a flowchart fell through to the markdown branch below and
      // rendered blk.markdown — which a flowchart does not have — so updating
      // one in place blanked the chart. The click and hover listeners live on
      // .block-content, which survives the repaint.
      paintFlowchart(content, blk);
    } else if (blockMd) {
      content.innerHTML = blockMd.render(blk.markdown || "");
      sanitizeFreeHtml(content);
      if (window.AnnotateGlossary) window.AnnotateGlossary.decorate(content);
    }
  }
  section.dataset.kind = newKind;
  section.dataset.version = String(blk.version ?? srvVer);
  setBlockLabel(section, blk);
  section._mine = Array.isArray(blk.mine) ? blk.mine : [];

  // A rewrite must not leave a card with stale panes: drop whatever was
  // there and repaint fresh from this version's anchors.
  const oldCol = section.querySelector(".code-col");
  if (oldCol) oldCol.remove();
  const freshCol = renderCodeColumn(blk);
  if (freshCol) {
    section.dataset.hasCode = "1";
    (section.querySelector(".block-body") || section).appendChild(freshCol);
  } else {
    delete section.dataset.hasCode;
  }

  clearUpdatingOverlay(section);
  return section;
}

// ── Boot ───────────────────────────────────────────────────────────────────

// subunits.js owns the round; script.js owns the poll loop and pendingEvents.
// The round has to land in pendingEvents or hasPendingRound() (and
// handleConsumedEvents' clearing on ack) never see it.
window.AnnotatePage = {
  // A round is in flight: the page is locked until Claude answers it.
  isBusy: () => document.body.classList.contains("is-busy"),
  // edit.js saved this version of a block: the reader's, not Claude's.
  wrote(blockId, body) { if (blockId && body && typeof body === "object") pageWrites.set(blockId, { ...body }); },
  // The page's own markdown rendering, sanitised as a card's is.
  renderMarkdown(text) {
    const div = document.createElement("div");
    div.innerHTML = blockMd ? blockMd.render(text || "") : "";
    if (!blockMd) div.textContent = text || "";
    sanitizeFreeHtml(div);
    return div.innerHTML;
  },
  // Re-render one section from a block, as a server rewrite would.
  renderBlock(section, block, version) {
    const out = updateBlockContent(section, block, version);
    window.AnnotateSubunits?.repaintBlocks?.();
    document.dispatchEvent(new CustomEvent("annotate:rendered"));
    return out;
  },
  // The selection menu's Comment on a whole section opens the same rich
  // card the keyboard's `c` opens: one door for whole-section comments.
  openComment(blockId) {
    const section = document.querySelector(
      `section.block[data-block-id="${cssEsc(blockId)}"]`);
    if (section) openAnnotation(section, "comment", {});
  },
  registerRoundEvent(eventId, blockIds) {
    if (!eventId) return;
    pendingEvents.set(String(eventId), {
      round: true,
      blockIds: Array.isArray(blockIds) ? blockIds.slice() : [],
    });
    // The submit POST can resolve after the poll that first saw busy, in
    // which case the busy start edge already ran and found no round in
    // pendingEvents. Claim the open window here too.
    windowHadRound = true;
  },
};

WebCompanion.init({ onPollDelta });
loadAndRenderBlocks();
