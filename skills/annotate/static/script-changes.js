// annotate page code, part 8 of 9 (see script.js): what changed in a round
// and who changed it — the change bar, the chips and the diff pane.

// ── What changed, and who changed it ───────────────────────────────────────
//
// When a round is acked the page grows a bar reading
//   "<n> parts changed — <a> you asked for, <b> by the coherence sweep"
// and every changed card grows an attribution chip plus a "what changed"
// word diff against the pre-round snapshot (GET <base>/prev, Task 1).
//
// Attribution is DERIVED, never reported: any block whose version bumped
// that was NOT in the round this client submitted was moved by the sweep.
// Nothing on the wire has to tell us that, so nothing can drift or lie.

// Per-block versions as they stood when the current round was submitted.
// Sourced from the `lastVersions` map core.js already threads into this
// callback — a second version ledger kept here is exactly how the
// attribution would start lying — and captured at the busy false→true edge,
// the same instant the server writes blocks.prev.json. So the bar, the
// chips, and the diff all describe one moment.
let roundBaseVersions = null;
let wasBusy = false;
// Did the busy window we are currently inside actually contain a ROUND?
//
// `data.busy` is true while ANY event is unacked — a general comment or a
// choice pick raises it exactly like a round does. Without this gate every
// busy false→true→false cycle computed a change set, and computeChangeSet
// attributed it against `submittedBlockIds()` — the block ids of whatever
// round was submitted LAST. So a general comment two exchanges later grew a
// change bar for a round the user never fired, with "you asked" chips citing
// that stale round.
//
// Recomputed from pendingEvents at the busy START edge, which is
// authoritative: a round entry is only removed from that map when its ack
// lands. Also set by registerRoundEvent, because a round's POST can resolve
// AFTER the poll that first saw busy — in that race the start edge would
// have found nothing.
let windowHadRound = false;
const hasPendingRound = () => {
  for (const p of pendingEvents.values()) if (p.round) return true;
  return false;
};
// Set on the ack, consumed after the next reconcile: the diff needs the
// post-round markdown from /raw and the refreshed sections in the DOM.
let pendingChangeSet = null;

// Which blocks moved, and who moved them. The user's own set is whatever
// they submitted — captured at submit time in subunits.js, because
// clearRound() wipes the marks on ack and this is the only surviving
// record. Everything else that moved was the coherence sweep.
//
// A block that still reads as this page itself last saved it (the reader's
// own edit) is nobody's change to report, unless Claude wrote over it.
// Matched by content (every field the author writes), not by version:
// under load the daemon's version for a block can run ahead of the one its
// PUT answered with. Forgotten once a round's change set is applied.
const pageWrites = new Map();
const AUTHORED = ["markdown", "title", "change_note"];
const sameAsWritten = (w, b) => !!b && (w.kind || "markdown") === (b.kind || "markdown")
  && AUTHORED.every((k) => (w[k] ?? "") === (b[k] ?? ""));
function computeChangeSet(prevVersions, nextVersions) {
  const asked = new Set(window.AnnotateSubunits?.submittedBlockIds?.() || []);
  const changed = [];
  for (const [bid, v] of Object.entries(nextVersions || {})) {
    const before = prevVersions ? prevVersions[bid] : undefined;
    if (before !== undefined && v > before) {
      changed.push({ blockId: bid, bySweep: !asked.has(bid), from: before });
    }
  }
  return changed;
}

function renderChangeBar(changed) {
  document.getElementById("change-bar")?.remove();
  if (!changed.length) return;
  const swept = changed.filter(c => c.bySweep).length;
  const asked = changed.length - swept;
  const bar = document.createElement("div");
  bar.id = "change-bar";
  bar.className = "change-bar";
  bar.setAttribute("role", "status");
  const dot = document.createElement("span");
  dot.className = "cb-dot";
  const txt = document.createElement("span");
  const parts = [];
  if (asked) parts.push(`${asked} you asked for`);
  if (swept) parts.push(`${swept} by the coherence sweep`);
  txt.innerHTML = `<b>${changed.length} part${changed.length > 1 ? "s" : ""} changed</b>`
    + (parts.length ? ` — <span class="cb-split">${parts.join(", ")}</span>` : "");
  const nav = document.createElement("span");
  nav.className = "cb-nav";
  let idx = -1;
  const go = (d) => {
    if (!changed.length) return;
    idx = (idx + d + changed.length) % changed.length;
    // A queued question off screen is display:none and cannot be scrolled to.
    window.AnnotateChoiceQueue?.show(changed[idx].blockId);
    unfoldFor(changed[idx].blockId);
    document.querySelector(
      `section.block[data-block-id="${cssEsc(changed[idx].blockId)}"]`
    )?.scrollIntoView({ behavior: "smooth", block: "center" });
  };
  for (const [label, d] of [["↑ prev", -1], ["next ↓", 1]]) {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label;
    b.addEventListener("click", () => go(d));
    nav.appendChild(b);
  }
  const dis = document.createElement("button");
  dis.type = "button"; dis.textContent = "dismiss";
  dis.addEventListener("click", () => bar.remove());
  nav.appendChild(dis);
  bar.append(dot, txt, nav);
  const header = document.querySelector(".page-header");
  if (header) header.insertAdjacentElement("afterend", bar);
}

// Wipe last round's verdict. Called when the next round starts, so a card
// can never carry attribution earned two rounds ago.
function clearChangeAttribution() {
  // Drop the un-applied set too, not just the painted DOM. Otherwise: the
  // ack poll's /raw fetch fails, the set survives, and round 2's busy edge
  // clears the cards and then hands round 1's set to the very next /raw —
  // chips and a pane appear mid-round, labelled with round-1 versions but
  // diffed against round 2's snapshot, and they sit there until round 3.
  pendingChangeSet = null;
  document.getElementById("change-bar")?.remove();
  document.querySelectorAll("section.block").forEach(section => {
    section.querySelector(".attr-chip")?.remove();
    section.querySelector(".card-diff-toggle")?.remove();
    section.querySelector(".diff-pane")?.remove();
    delete section.dataset.diff;
  });
}

function markChangedCard(section, c) {
  const head = section.querySelector(".block-label");
  if (!head) return;
  head.querySelector(".attr-chip")?.remove();
  head.querySelector(".card-diff-toggle")?.remove();
  const chip = document.createElement("span");
  chip.className = "attr-chip " + (c.bySweep ? "a-sweep" : "a-you");
  chip.textContent = c.bySweep ? "sweep" : "you asked";
  chip.title = c.bySweep
    ? "Rewritten by the coherence sweep — you did not mark this part"
    : "Rewritten because you marked it in this round";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "card-diff-toggle";
  toggle.textContent = "what changed";
  toggle.setAttribute("aria-pressed", "false");
  toggle.addEventListener("click", (ev) => {
    // The label carries the fold button and the control strip; don't let a
    // diff toggle also trip whatever else listens up there.
    ev.stopPropagation();
    const open = section.dataset.diff === "open";
    section.dataset.diff = open ? "" : "open";
    toggle.setAttribute("aria-pressed", open ? "false" : "true");
  });
  // By the title, not after the control strip a frame head carries.
  const title = head.querySelector(".block-heading-text");
  if (title) title.after(chip, toggle);
  else head.prepend(chip, toggle);
}

// ── The pane ──────────────────────────────────────────────────────────────
//
// The diff itself lives in static/diff.js, as pure functions over two
// strings, and is covered by tests/diff_engine.test.cjs. Everything here is
// DOM: materialise what the engine returned, wire the three controls, and
// stay out of the algorithm's way.
//
// The pane offers two views of the same rows because they answer different
// questions and both get asked:
//
//   reader  the new text as prose, additions tinted, deletions folded into
//           a chip. Answers "what does it say now".
//   diff    paragraph by paragraph, both sides on show, unchanged runs
//           collapsed. Answers "what exactly moved", and is where you go
//           the moment you do not trust the reader view.
//
// Reader is the default: it is the question people arrive with. The choice
// is remembered, because someone who wants the diff view wants it for the
// whole round, not for one card.

const DIFF_VIEW_KEY = "annotate.diffview";
const DIFF_VIEWS = [["reader", "reader"], ["diff", "diff"]];
let diffView = (() => {
  try {
    const v = localStorage.getItem(DIFF_VIEW_KEY);
    return DIFF_VIEWS.some(([id]) => id === v) ? v : "reader";
  } catch { return "reader"; }
})();

// vnode -> DOM. A string kid is ALWAYS a text node, which is what keeps
// arbitrary block markdown from becoming markup: there is no path here that
// parses HTML, so a block containing "<img onerror=...>" renders those
// characters and nothing else. diff.js builds the tree; nobody builds an
// HTML string anywhere along the way.
function materialize(node) {
  if (typeof node === "string") return document.createTextNode(node);
  const el = document.createElement(node.tag);
  if (node.cls) el.className = node.cls;
  for (const k of Object.keys(node.attrs || {})) el.setAttribute(k, node.attrs[k]);
  for (const kid of node.kids || []) el.appendChild(materialize(kid));
  return el;
}

// Recognised change_note line labels, in the order the contract documents
// them (see references/handling-events.md § "Explaining a change").
const CHANGE_NOTE_LABELS = ["Why:", "Lost:"];

// Task 5's per-block change note: free-form text Claude may attach to a
// rewrite, optionally carrying a `Why:` line and — for a compact that
// dropped detail — a `Lost:` line. Rendered ABOVE the diff, not below it: a
// one-line reason makes the marks underneath legible, and on a compact the
// `Lost:` line is the single most valuable thing in the pane and the one
// place a user can ever learn what was discarded. It should not be the last
// thing you scroll to.
//
// Each line gets its own row rather than one blob: a fixed leading label
// would double up against a note that already starts with "Why:", and
// folding a `Lost:` line into the same paragraph buries it. The field is
// optional and free-form, so this must still render sensibly with no
// recognised label, extra blank lines, or only a `Why:` line.
function renderChangeNote(note) {
  if (typeof note !== "string" || !note.trim()) return null;
  const why = document.createElement("div");
  why.className = "diff-why";
  for (const rawLine of note.trim().split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const row = document.createElement("div");
    row.className = "diff-why-line";
    const label = CHANGE_NOTE_LABELS.find(l => line.startsWith(l));
    if (label) {
      row.classList.add(label === "Lost:" ? "diff-lost" : "diff-reason");
      const lbl = document.createElement("b");
      lbl.textContent = label + " ";
      row.append(lbl, document.createTextNode(line.slice(label.length).trim()));
    } else {
      row.appendChild(document.createTextNode(line));
    }
    why.appendChild(row);
  }
  return why.children.length ? why : null;
}

function renderViewSwitch() {
  const wrap = document.createElement("span");
  wrap.className = "diff-views";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "How to show the change");
  for (const [id, label] of DIFF_VIEWS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "diff-view-btn";
    b.dataset.view = id;
    b.textContent = label;
    b.setAttribute("aria-pressed", String(id === diffView));
    wrap.appendChild(b);
  }
  return wrap;
}

// Repaint every open pane's switch after a choice, so the setting reads as
// a document-wide preference rather than a per-card accident.
function applyDiffView(view) {
  diffView = view;
  try { localStorage.setItem(DIFF_VIEW_KEY, view); } catch { /* private mode */ }
  document.querySelectorAll(".diff-pane").forEach(pane => {
    pane.dataset.view = view;
    pane.querySelectorAll(".diff-view-btn").forEach(b => {
      b.setAttribute("aria-pressed", String(b.dataset.view === view));
    });
  });
}

function renderDiffPane(section, c, blk, before) {
  section.querySelector(".diff-pane")?.remove();
  const now = blk.markdown || "";
  if (now === before) return;

  const D = window.AnnotateDiff;
  // No engine (a stale cached page, a blocked asset) is not a reason to
  // lose the attribution chip and the change note as well.
  const rows = D ? D.alignUnits(D.splitUnits(before), D.splitUnits(now)) : null;

  const pane = document.createElement("div");
  pane.className = "diff-pane";
  pane.dataset.view = diffView;

  const h = document.createElement("div");
  h.className = "diff-h";
  const label = document.createElement("span");
  label.textContent = `changed from v${c.from}`
    + (c.bySweep ? " — you did not mark this part" : "");
  const spacer = document.createElement("span");
  spacer.className = "diff-h-space";
  h.append(label, spacer);
  if (rows) h.appendChild(renderViewSwitch());
  pane.appendChild(h);

  const note = renderChangeNote(blk.change_note);
  if (note) pane.appendChild(note);

  if (rows) {
    pane.appendChild(materialize(D.renderReader(rows)));
    pane.appendChild(materialize(D.renderUnified(rows)));
  }

  const body = section.querySelector(".block-body");
  if (body) body.insertAdjacentElement("afterend", pane);
  else section.appendChild(pane);
}

// One delegated listener for every pane on the page: panes come and go on
// every round, and re-binding per pane is how listeners leak.
document.addEventListener("click", (ev) => {
  const view = ev.target.closest?.(".diff-view-btn");
  if (view) { ev.stopPropagation(); applyDiffView(view.dataset.view); return; }

  // Open a folded deletion in place. One-way on purpose: having asked what
  // was cut, you are reading the answer, and a chip that re-hides it invites
  // clicking twice and losing it again.
  const cut = ev.target.closest?.(".d-cut");
  if (cut) {
    ev.stopPropagation();
    const del = document.createElement("del");
    del.className = "d-cut-open";
    del.textContent = cut.getAttribute("data-cut") || "";
    cut.replaceWith(del);
    return;
  }

  const fold = ev.target.closest?.(".d-fold");
  if (fold) {
    ev.stopPropagation();
    const box = fold.nextElementSibling;
    if (!box || !box.classList.contains("d-fold-body")) return;
    const opening = box.hasAttribute("hidden");
    if (opening) box.removeAttribute("hidden"); else box.setAttribute("hidden", "");
    fold.setAttribute("aria-expanded", String(opening));
    const n = box.children.length;
    fold.textContent = opening
      ? "▾ hide unchanged"
      : "… " + n + " unchanged paragraph" + (n > 1 ? "s" : "");
  }
});


// The pre-round snapshot: the document as it stood when the round was
// queued, which is the only record of what a block used to say. Read-only,
// so it works on a shared read-only link too.
//
// `<base>/prev` is NOT a route on the daemon and 404s if you curl it. It is
// synthesised in the page by compat.js, which patches window.fetch and reads
// the __prev__ item push.py writes. That is by design, and testing it from
// outside the browser has already been mistaken once for three silently
// broken features — see test_smoke_route_shim.py.
async function loadPrev() {
  try {
    const r = await fetch(BASE + "prev", { cache: "no-store" });
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.ok ? d.blocks : null;
  } catch { return null; }
}

async function applyChangeSet(changed, doc) {
  renderChangeBar(changed);
  const byId = new Map((doc.blocks || []).map(b => [b.id, b]));
  const prev = await loadPrev();
  for (const c of changed) {
    // Per block, so one pathological block (a diff that still blows up
    // despite the cell cap) costs its own pane and nothing else's.
    try {
      const section = document.querySelector(
        `section.block[data-block-id="${cssEsc(c.blockId)}"]`);
      if (!section) continue;
      markChangedCard(section, c);
      const blk = byId.get(c.blockId);
      const before = prev ? prev[c.blockId] : null;
      // No snapshot (first round on an old session, or a non-markdown block)
      // means no diff — the chip and the bar still stand on their own.
      if (blk && typeof before === "string") renderDiffPane(section, c, blk, before);
    } catch (e) {
      console.warn("diff failed for block", c.blockId, e);
    }
  }
}
