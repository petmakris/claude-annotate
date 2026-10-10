// skills/annotate/static/edit.js
/* Editing a section in place.
 *
 * `e` on the j/k section, or ✎ in the selection menu, turns that section
 * into its editor. Two views of one text:
 *   Rich   — the rendered section itself, editable (vendor/rich.min.js,
 *            ProseMirror). Saving replays the edit onto the stored bytes, so
 *            a one-word edit is a one-word change.
 *   Source — the exact stored text (vendor/editor.min.js, CodeMirror).
 * Rich is the default; a section Rich cannot show opens in Source and says
 * why. Both bundles load the first time they are needed. A switch carries
 * the current view's getText() into the other.
 *
 * What the reader saves is final: the stored markdown becomes exactly the
 * view's text, sent with If-Match on the version the editor opened at, so a
 * section Claude rewrote meanwhile is refused (412) and offered as a choice,
 * never overwritten.
 *
 * One section at a time. The rendered text stays in the DOM, hidden by
 * `data-editing`, which is also what tells script.js's reconcile to hold a
 * rewrite on the section (`_pendingBlock`) until the editor closes. The Rich
 * view sits beside it as a `.block-content.ed-rich`, so the page's own
 * styles lay it out exactly as the section was.
 *
 * An open section is HELD: the `__holds__` item names it, with a heartbeat,
 * and push.py keeps the reader's stored version of a held section instead
 * of writing Claude's over it. Another tab finds the hold and does not open
 * the same section.
 */
(function () {
  "use strict";

  const BASE = new URL("./", document.currentScript ? document.currentScript.src : location.href);
  const EDITOR_SRC = new URL("vendor/editor.min.js", BASE).href;
  const RICH_SRC = new URL("vendor/rich.min.js", BASE).href;
  // Answered with their own controls, or pictures: no markdown to edit.
  const NOT_TEXT = ["choice", "sequence", "diagram", "flowchart", "mockup"];
  const HINT_SOURCE = "⌘/ rich ⇄ source · ⌘S save · F6 bar · esc done";
  const HINT_RICH = "⌘B bold · ⌘I italic · ⌘E code · ⌘K link · ## heading · - list · F6 bar · esc done";
  const NO_RICH = "Rich editing isn't available for this part — showing the source";
  const ICON_EDIT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9"/>'
    + '<path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>';

  let cur = null;          // the open editor's state
  let busyOpening = false;
  const savedFns = [];

  // ── the daemon ──────────────────────────────────────────────────────────
  // The contract and the owner token, from daemon-http.js.
  const headers = (extra) => window.AnnotateDaemonHttp.headers(extra);

  // {status, json, text}; a 412 or a 400 is an answer, not an exception.
  // Only a network failure throws.
  async function request(method, path, body, extra) {
    const opts = { method, cache: "no-store",
                   headers: headers(Object.assign(body ? { "Content-Type": "application/json" } : {}, extra || {})) };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const r = await fetch(window.WebCompanion.api.BASE + path, opts);
    const text = await r.text();
    let json = null;
    try { json = text ? JSON.parse(text) : null; } catch (_) {}
    noteClock(r);
    return { status: r.status, ok: r.ok, json, text };
  }
  const itemPath = (id) => "items/" + encodeURIComponent(id);

  // ── holds ───────────────────────────────────────────────────────────────
  // `__holds__` is {block_id: {opened_at, heartbeat_at, tab}} in epoch
  // seconds, shared by every tab on the page and read by push.py. It is
  // changed read-modify-write under If-Match, so two tabs never drop each
  // other's entry. A hold whose heartbeat is older than 30 minutes is a dead
  // tab's, and everyone ignores it.
  const HOLDS = "__holds__";
  const HOLD_STALE_S = 1800;
  let heartbeatMs = 60000;
  // This tab's name in the holds. Kept for the tab's life, reloads included,
  // so a hold a reload failed to release is recognised as this tab's and
  // released when the page loads again (below), rather than refusing the
  // reader their own section for half an hour.
  const TAB_KEY = "annotate.edit.tab";
  const newTab = () => {
    const id = Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
    try { sessionStorage.setItem(TAB_KEY, id); } catch (_) {}
    return id;
  };
  let TAB = (() => {
    try { const had = sessionStorage.getItem(TAB_KEY); if (had) return had; } catch (_) {}
    return newTab();
  })();
  // The times are the daemon's clock, as push.py reads them: a phone's clock
  // is not the daemon's. Learned from each response's Date header.
  let skew = 0;
  function noteClock(r) {
    const d = Date.parse((r.headers && r.headers.get("Date")) || "");
    if (!Number.isNaN(d)) skew = d - Date.now();
  }
  const now = () => Math.floor((Date.now() + skew) / 1000);
  const fresh = (h) => !!h && typeof h === "object" && now() - (Number(h.heartbeat_at) || 0) <= HOLD_STALE_S;
  // The last holds this tab read or wrote, for the release on pagehide,
  // which cannot wait for a read.
  let holdsSeen = null;     // {body, version}

  // Apply `change` to the stored holds. `change(body)` edits a copy and
  // returns "refuse" to stop, "same" when there is nothing to write.
  // Resolves to "ok", "refused", or "failed".
  async function changeHolds(change) {
    for (let tries = 0; tries < 5; tries++) {
      let g;
      try { g = await request("GET", itemPath(HOLDS)); } catch (_) { return "failed"; }
      let body = {}, version = 0;
      if (g.ok && g.json) {
        const b = g.json.body;
        if (b && typeof b === "object" && !Array.isArray(b)) body = Object.assign({}, b);
        version = g.json.version || 0;
      } else if (g.status !== 404) return "failed";
      holdsSeen = { body: Object.assign({}, body), version };
      const verdict = change(body);
      if (verdict === "refuse") return "refused";
      if (verdict === "same") return "ok";
      // Dead tabs' entries go while the item is being written anyway.
      for (const [k, v] of Object.entries(body)) if (!fresh(v)) delete body[k];
      let p;
      try { p = await request("PUT", itemPath(HOLDS), body, { "If-Match": String(version) }); }
      catch (_) { return "failed"; }
      if (p.ok) { holdsSeen = { body, version: (p.json && p.json.version) || version + 1 }; return "ok"; }
      if (p.status !== 412) return "failed";
    }
    return "failed";
  }

  // Take the hold on a section, or "refused" when another tab has it.
  function hold(blockId, openedAt) {
    return changeHolds((body) => {
      const h = body[blockId];
      if (fresh(h) && h.tab !== TAB) return "refuse";
      body[blockId] = { opened_at: openedAt, heartbeat_at: now(), tab: TAB };
      return "write";
    });
  }

  function release(blockId) {
    return changeHolds((body) => {
      if (!body[blockId] || body[blockId].tab !== TAB) return "same";
      delete body[blockId];
      return "write";
    });
  }

  // A heartbeat refused because another tab now holds the section (this
  // one's hold went stale, say) is said in the bar, not dropped: the reader
  // keeps editing, and If-Match still keeps their save off a newer version.
  function startHeartbeat(st) {
    clearInterval(st.beat);
    st.beat = setInterval(async () => {
      if (cur !== st) { clearInterval(st.beat); return; }
      const got = await hold(st.blockId, st.openedAt);
      if (cur !== st || got === "failed") return;
      const lost = got === "refused";
      if (lost !== !!st.holdLost) { st.holdLost = lost; paintBar(st); }
    }, heartbeatMs);
  }

  // A hold this tab left behind (a pagehide release that never landed) is
  // released when the page loads again. A duplicated tab inherits this
  // tab's name with its sessionStorage, so first ask: when another live
  // page answers to the name, this one takes a new name and releases
  // nothing.
  const chan = typeof BroadcastChannel === "function"
    ? new BroadcastChannel("annotate-edit:" + location.pathname) : null;
  let askingName = false, nameTaken = false;
  if (chan) {
    chan.onmessage = (ev) => {
      const m = ev.data || {};
      if (m.who === TAB && m.ask) chan.postMessage({ who: TAB, here: true });
      else if (m.who === TAB && m.here && askingName) nameTaken = true;
    };
  }
  function releaseLeftovers() {
    if (readOnly() || !window.WebCompanion?.api) return;
    changeHolds((body) => {
      let n = 0;
      for (const [k, v] of Object.entries(body)) {
        if (v && v.tab === TAB && !(cur && cur.blockId === k)) { delete body[k]; n++; }
      }
      return n ? "write" : "same";
    }).catch(() => {});
  }
  if (chan) {
    askingName = true;
    chan.postMessage({ who: TAB, ask: true });
    setTimeout(() => {
      askingName = false;
      if (nameTaken) TAB = newTab();
      else releaseLeftovers();
    }, 300);
  } else setTimeout(releaseLeftovers, 0);

  // Another tab changed the holds: keep the copy pagehide releases from
  // current, so its conditional write is not refused for a stale version.
  document.addEventListener("annotate:holds", (ev) => {
    const v = ev.detail && ev.detail.version;
    if (!cur || (holdsSeen && holdsSeen.version === v)) return;
    request("GET", itemPath(HOLDS)).then((g) => {
      if (g.ok && g.json && g.json.body && typeof g.json.body === "object") {
        holdsSeen = { body: Object.assign({}, g.json.body), version: g.json.version || 0 };
      }
    }).catch(() => {});
  });

  // The page is going away: release the hold with a request that outlives
  // it. It cannot read first, so it writes the holds last seen, minus this
  // tab's entry, on their version; if another tab wrote since, it is refused
  // and the hold simply goes stale. (sendBeacon cannot carry the contract
  // and token headers the daemon requires.)
  window.addEventListener("pagehide", () => {
    if (!cur || !holdsSeen) return;
    const body = Object.assign({}, holdsSeen.body);
    if (!body[cur.blockId] || body[cur.blockId].tab !== TAB) return;
    delete body[cur.blockId];
    clearInterval(cur.beat);
    cur.released = true;
    try {
      fetch(window.WebCompanion.api.BASE + itemPath(HOLDS), {
        method: "PUT", keepalive: true, cache: "no-store", body: JSON.stringify(body),
        headers: headers({ "Content-Type": "application/json", "If-Match": String(holdsSeen.version) }),
      }).catch(() => {});
    } catch (_) {}
  });
  // Back from the back/forward cache with the editor still open: hold again.
  window.addEventListener("pageshow", (ev) => {
    if (!ev.persisted || !cur || !cur.released) return;
    cur.released = false;
    hold(cur.blockId, cur.openedAt);
    startHeartbeat(cur);
  });

  // ── unsaved changes ─────────────────────────────────────────────────────
  // While the editor holds words not yet saved, leaving the page warns, and
  // the round's Submit waits (as it does for an open comment box): the
  // round would tell Claude about an edit the store does not have yet.
  function warnUnload(ev) {
    ev.preventDefault();
    ev.returnValue = "";
    return "";
  }
  let unsaved = false;
  function syncUnsaved() {
    const on = !!(cur && cur.handle && cur.handle.getText() !== cur.body.markdown);
    if (on === unsaved) return;
    unsaved = on;
    if (on) window.addEventListener("beforeunload", warnUnload);
    else window.removeEventListener("beforeunload", warnUnload);
    document.body.classList.toggle("has-edit-draft", on);
    window.AnnotateSubunits?.renderDock?.();
  }

  function markUnsaved() {
    if (unsaved) return;
    unsaved = true;
    window.addEventListener("beforeunload", warnUnload);
    document.body.classList.add("has-edit-draft");
    window.AnnotateSubunits?.renderDock?.();
  }

  // ── drafts ──────────────────────────────────────────────────────────────
  // Words not yet saved are kept in localStorage as they are typed, so a
  // phone that drops the tab does not drop them. Keyed by the page, the
  // section and the version the text was typed against: a draft is only
  // offered over the text it was written on. Cleared by a save, a discard
  // and Take theirs. Storage can be missing or full; then there is no draft.
  const DRAFT_PREFIX = "annotate.edit.draft.";
  const draftKey = (st, version) => DRAFT_PREFIX
    + JSON.stringify([window.WebCompanion?.api?.BASE || location.pathname, st.blockId,
                      version === undefined ? st.version : version]);
  let draftTimer = 0;
  function readDraft(st) {
    try {
      const v = localStorage.getItem(draftKey(st));
      return typeof v === "string" ? v : null;
    } catch (_) { return null; }
  }
  function clearDraft(st, version) {
    clearTimeout(draftTimer);
    try { localStorage.removeItem(draftKey(st, version)); } catch (_) {}
  }
  function writeDraft(st) {
    clearTimeout(draftTimer);
    if (cur !== st || !st.handle || st.phase === "draft") return;
    const text = st.handle.getText();
    try {
      if (text === st.body.markdown) localStorage.removeItem(draftKey(st));
      else localStorage.setItem(draftKey(st), text);
    } catch (_) {}
  }
  function queueDraft(st) {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => writeDraft(st), 300);
  }
  // A phone suspends a hidden tab without warning: write now.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden" && cur) writeDraft(cur);
  });
  window.addEventListener("pagehide", () => { if (cur) writeDraft(cur); });

  // ── the bundles ─────────────────────────────────────────────────────────
  const loading = {};
  function loadBundle(src, global, why) {
    if (window[global]) return Promise.resolve(window[global]);
    if (!loading[global]) {
      loading[global] = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        const fail = async () => {
          loading[global] = null;
          s.remove();
          // A script tag does not say why; a second request does.
          let status = "network error";
          try { status = String((await fetch(src, { method: "HEAD", cache: "no-store" })).status); } catch (_) {}
          reject(new Error(why(status)));
        };
        s.onload = () => (window[global] ? resolve(window[global]) : fail());
        s.onerror = fail;
        document.head.appendChild(s);
      });
    }
    return loading[global];
  }
  const loadEditor = () => loadBundle(EDITOR_SRC, "AnnotateEditor", (st) => `The editor could not load (${st})`);
  const loadRich = () => loadBundle(RICH_SRC, "AnnotateRich",
    (st) => `Rich editing could not load (${/^\d+$/.test(st) ? "HTTP " + st : st})`);

  // ── notices ─────────────────────────────────────────────────────────────
  let toastTimer = 0;
  function say(text) {
    if (!text) return;
    let t = document.querySelector(".ed-toast");
    if (!t) {
      t = document.createElement("div");
      t.className = "ed-toast";
      t.setAttribute("role", "status");
      document.body.appendChild(t);
    }
    t.textContent = text;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.remove(), 3200);
  }

  // ── what may be edited ──────────────────────────────────────────────────
  function sectionFor(id) {
    return document.querySelector(`main.prose section.block[data-block-id="${CSS.escape(id)}"]`);
  }
  function readOnly() {
    return document.body.classList.contains("read-only") || window.WebCompanion?.writable === false;
  }
  // Why this part cannot be opened now, or "" when it can.
  function refusal(section) {
    if (!section) return "This part is no longer on the page";
    if (NOT_TEXT.includes(section.dataset.kind || "markdown")) return "This part can't be edited as text";
    if (document.body.dataset.highlighter === "on") return "Turn off the highlighter to edit";
    if (window.AnnotatePage?.isBusy?.()) return "Claude is working — edit when it finishes";
    if (section.classList.contains("is-updating")) return "Claude is rewriting this part";
    return "";
  }

  // ── the cursor at the selected words ────────────────────────────────────
  // The anchor counts rendered text; the editor holds markdown. The words
  // are found in the markdown, the occurrence whose surroundings best match
  // the anchor's context; failing that, its first word.
  function offsetFor(md, anchor) {
    if (!anchor || !anchor.selected_text) return 0;
    const find = (needle) => {
      const hits = [];
      for (let i = md.indexOf(needle); i >= 0; i = md.indexOf(needle, i + 1)) hits.push(i);
      if (hits.length <= 1) return hits.length ? hits[0] : -1;
      const pre = (anchor.prefix || "").replace(/\s+/g, " ");
      const score = (i) => {
        const before = md.slice(Math.max(0, i - 200), i).replace(/[*_`#>\[\]]/g, "").replace(/\s+/g, " ");
        let n = 0;
        while (n < pre.length && n < before.length && pre[pre.length - 1 - n] === before[before.length - 1 - n]) n++;
        return n;
      };
      return hits.reduce((best, i) => (score(i) > score(best) ? i : best), hits[0]);
    };
    let at = find(anchor.selected_text);
    if (at < 0) {
      const word = (anchor.selected_text.match(/[^\s*_`]{2,}/) || [""])[0];
      at = word ? find(word) : -1;
    }
    return at < 0 ? 0 : at;
  }

  // ── the bar ─────────────────────────────────────────────────────────────
  function btn(act, label, cls) {
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.act = act;
    b.className = cls || "ed-btn";
    b.textContent = label;
    b.addEventListener("mousedown", (e) => e.preventDefault());
    return b;
  }

  function paintBar(st) {
    syncUnsaved();
    const bar = st.bar;
    const hadField = !!(document.activeElement && document.activeElement.classList.contains("ed-link")
                        && bar.contains(document.activeElement));
    // The state words are one live region for the editor's life, so a screen
    // reader hears each change (Saving…, the conflict, the error); a region
    // made anew on every paint is not announced. Everything else is redrawn.
    if (!st.live) {
      st.live = document.createElement("span");
      st.live.setAttribute("role", "status");
      st.live.setAttribute("aria-live", "polite");
    }
    for (const c of [...bar.childNodes]) if (c !== st.live) c.remove();
    bar.className = "ed-bar";
    const dot = document.createElement("span");
    dot.className = "ed-dot";
    const state = st.live;
    state.className = "ed-state";
    const sp = document.createElement("span");
    sp.className = "ed-sp";
    const msg = (text) => { state.className = "ed-msg"; state.textContent = text; return state; };
    // Lay the bar out around the live region without moving it.
    const lay = (...nodes) => {
      if (!state.parentNode) bar.appendChild(state);
      const i = nodes.indexOf(state);
      for (const n of nodes.slice(0, i)) bar.insertBefore(n, state);
      for (const n of nodes.slice(i + 1)) bar.appendChild(n);
    };

    if (st.phase === "draft") {
      dot.classList.add("ed-dot--warn");
      const restore = btn("restore-draft", "Restore your unsaved text", "ed-btn ed-btn--primary");
      const drop = btn("discard-draft", "Discard it");
      restore.addEventListener("click", async () => {
        const text = readDraft(st);
        st.phase = "edit";
        if (text !== null) await restoreText(st, text);
        paintBar(st);
        v_focus(st);
      });
      drop.addEventListener("click", () => { clearDraft(st); st.phase = "edit"; paintBar(st); v_focus(st); });
      lay(dot, msg("You have text here that was never saved."), sp, drop, restore);
      return;
    }
    if (st.phase === "confirm") {
      dot.classList.add("ed-dot--warn");
      state.textContent = "Discard your changes?";
      const yes = btn("confirm-discard", "Discard", "ed-btn ed-btn--danger");
      const no = btn("keep-editing", "Keep editing");
      yes.addEventListener("click", () => discard(st));
      no.addEventListener("click", () => { st.phase = "edit"; paintBar(st); v_focus(st); });
      lay(dot, state, sp, yes, no);
      no.focus({ preventScroll: true });
      return;
    }
    if (st.phase === "conflict") {
      bar.classList.add("ed-bar--conflict");
      dot.classList.add("ed-dot--warn");
      const show = btn("show-diff", st.diffShown ? "Hide what changed" : "Show what changed");
      const theirs = btn("take-theirs", "Take theirs");
      const copy = copyButton(st);
      const mine = btn("keep-mine", "Keep mine", "ed-btn ed-btn--primary");
      show.addEventListener("click", () => toggleDiff(st));
      theirs.addEventListener("click", () => takeTheirs(st));
      mine.addEventListener("click", () => keepMine(st));
      lay(dot, msg("This part changed while you were editing. Nothing has been overwritten."), sp, show, theirs, copy, mine);
      return;
    }
    if (st.phase === "error") {
      bar.classList.add("ed-bar--conflict");
      dot.classList.add("ed-dot--warn");
      const retry = btn("retry", "Retry", "ed-btn ed-btn--primary");
      retry.addEventListener("click", () => done(st));
      const discardB = btn("discard", "Discard");
      discardB.addEventListener("click", () => { st.phase = "confirm"; paintBar(st); });
      lay(dot, msg(`Not saved — ${st.error}`), sp, discardB, retry);
      return;
    }
    if (st.phase === "removed") {
      bar.classList.add("ed-bar--conflict", "ed-bar--removed");
      dot.classList.add("ed-dot--warn");
      const copy = copyButton(st);
      const closeB = btn("close", "Close", "ed-btn ed-btn--primary");
      closeB.addEventListener("click", () => close(st));
      lay(dot, msg("This part was removed. Copy your text before closing"), sp, copy, closeB);
      return;
    }

    const dirty = st.handle && st.handle.getText() !== st.body.markdown;
    if (st.phase === "saving") state.textContent = "Saving…";
    else state.textContent = dirty ? "Unsaved changes" : "Editing";
    if (dirty) dot.classList.add("ed-dot--dirty");
    const seg = document.createElement("span");
    seg.className = "ed-seg";
    seg.setAttribute("role", "group");
    seg.setAttribute("aria-label", "View");
    for (const [view, label] of [["rich", "Rich"], ["source", "Source"]]) {
      const b = btn("view", label, "");
      b.dataset.view = view;
      b.setAttribute("aria-pressed", String(st.view === view));
      if (st.view === view) b.classList.add("is-on");
      b.addEventListener("click", async () => { await setView(st, view); if (cur === st) v_focus(st); });
      seg.appendChild(b);
    }
    let note = document.createElement("span");
    note.className = "ed-hint";
    note.textContent = st.view === "rich" ? HINT_RICH : HINT_SOURCE;
    const msgNote = (text) => {
      note = document.createElement("span");
      note.className = "ed-msg ed-note";
      note.textContent = text;
    };
    if (st.holdLost) msgNote("Another tab took this part — your saves still won't overwrite it");
    else if (st.view === "source" && st.richNote) msgNote(st.richNote);
    if (st.linking) note = linkField(st);
    const check = btn("check", "What will be saved");
    check.setAttribute("aria-pressed", String(!!st.checkBox));
    if (st.checkBox) check.classList.add("is-on");
    check.addEventListener("click", () => toggleCheck(st));
    const discardB = btn("discard", "Discard");
    discardB.addEventListener("click", () => {
      if (st.handle.getText() === st.body.markdown) return discard(st);
      st.phase = "confirm";
      paintBar(st);
    });
    const doneB = btn("done", "Done", "ed-btn ed-btn--primary");
    doneB.addEventListener("click", () => done(st));
    if (st.phase === "saving") { discardB.disabled = true; doneB.disabled = true; }
    lay(dot, state, seg, note, sp, check, discardB, doneB);
    // The field takes focus when ⌘K opens it, or back after a repaint that
    // rebuilt it under the reader's typing; never otherwise, so a field the
    // reader left open cannot pull later keystrokes into itself.
    if (st.linking && (st.linking.focus || hadField)) {
      st.linking.focus = false;
      note.querySelector("input").focus({ preventScroll: true });
    }
  }

  const v_focus = (st) => st.handle.focus();

  // ── ⌘K: the link field ──────────────────────────────────────────────────
  // Rich asks for a link's address here, in the bar, never in a browser
  // prompt. Enter applies it to the selection (an empty field on a link
  // removes the link); Esc leaves the text as it was. Either way the caret
  // goes back to the words.
  function askLink(st) {
    if (cur !== st || st.phase !== "edit" || st.view !== "rich") return;
    const at = st.handle.linkAt();
    st.linking = { href: at ? at.href : "", focus: true };
    st.handle.holdSelection(true);
    paintBar(st);
  }
  // The field is closed without a link: the reader went elsewhere.
  function dropLink(st) {
    if (!st.linking) return;
    st.linking = null;
    if (st.view === "rich") st.handle.holdSelection(false);
    if (cur === st) paintBar(st);
  }
  function linkField(st) {
    const wrap = document.createElement("span");
    wrap.className = "ed-linkwrap";
    const input = document.createElement("input");
    input.type = "url";
    input.className = "ed-link";
    input.placeholder = "https://…  Enter to link · esc cancel";
    input.setAttribute("aria-label", "Link address");
    input.spellcheck = false;
    input.value = st.linking.href;
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      const href = input.value.trim();
      const had = st.linking.href;
      st.linking = null;
      st.handle.holdSelection(false);
      paintBar(st);
      if (href || had) st.handle.setLink(href || null);
      v_focus(st);
    });
    // Focus going anywhere but the bar (a click back into the text) closes
    // the field; the words keep no link.
    input.addEventListener("blur", (ev) => {
      if (ev.relatedTarget && st.bar.contains(ev.relatedTarget)) return;
      setTimeout(() => { if (st.linking && document.activeElement !== input) dropLink(st); }, 0);
    });
    wrap.appendChild(input);
    return wrap;
  }
  function cancelLink(st) {
    dropLink(st);
    v_focus(st);
  }

  // Only the dot and the words change while typing; repainting the whole
  // bar would take focus from a button the reader is on.
  function paintDirty(st) {
    if (st.phase !== "edit") return;
    const dirty = st.handle.getText() !== st.body.markdown;
    st.bar.querySelector(".ed-dot")?.classList.toggle("ed-dot--dirty", dirty);
    const s = st.bar.querySelector(".ed-state");
    if (s) s.textContent = dirty ? "Unsaved changes" : "Editing";
  }

  // Copy the reader's text; when the clipboard refuses, the text is
  // selected in the editor so ⌘C still takes it.
  function copyButton(st) {
    const copy = btn("copy", "Copy");
    copy.addEventListener("click", async () => {
      const ok = await copyText(st.handle.getText());
      if (!ok) st.handle.selectAll();
      copy.textContent = ok ? "Copied" : "Selected — press ⌘C";
    });
    return copy;
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.cssText = "position:fixed;top:0;left:0;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch (_) { return false; }
  }

  // ── views ───────────────────────────────────────────────────────────────
  // Each view is wrapped in the same small handle, so everything else (the
  // save, drafts, the conflict, holds, `mine`) reads getText() and never
  // asks which view is open.
  function richHandle(h, el) {
    return {
      kind: "rich", el, view: h.view,
      getText: () => h.getText(),
      setText: (t) => h.setText(t),
      focus: () => h.focus(),
      isFocused: () => h.isFocused(),
      focusAt: (offset) => h.focusAt(offset),
      stats: () => h.stats(),
      linkAt: () => h.linkAt(),
      setLink: (href) => h.setLink(href),
      holdSelection: (on) => h.holdSelection(on),
      selectAll() { h.focus(); document.execCommand("selectAll"); },
      destroy: () => h.destroy(),
    };
  }
  function sourceHandle(h, el) {
    const v = h.view;
    return {
      kind: "source", el, view: v,
      getText: () => h.getText(),
      setText(t) { v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: t } }); },
      focus: () => v.contentDOM.focus({ preventScroll: true }),
      isFocused: () => v.hasFocus,
      focusAt: (offset) => h.focusAt(offset),
      selectAll() { v.dispatch({ selection: { anchor: 0, head: v.state.doc.length } }); v.focus(); },
      destroy: () => h.destroy(),
    };
  }

  // Why Rich cannot show `text`, or "".
  function richRefusal(st, text) {
    if (!window.AnnotateRich) return st.richNote || "Rich editing is not loaded";
    try {
      return window.AnnotateRich.canShow(text, window.AnnotateRich.formatOf(text)) || "";
    } catch (e) { return e.message || "this part couldn't be read"; }
  }

  // The page's highlighter, as script.js's highlightFence calls it.
  function paintCode(code, lang) {
    if (!window.CodePaint) return null;
    const tag = String(lang || "").trim().split(/\s+/)[0];
    return window.CodePaint.paint(code, { lang: tag });
  }

  // Rich's getText() replays the edit onto the stored bytes, which costs
  // more than a keystroke should on a long section: the bar, the unsaved
  // state and What will be saved catch up a moment after typing stops.
  // (A draft is written on pagehide whatever the timer.)
  let changeTimer = 0;
  function changed(st) {
    if (cur !== st) return;
    clearTimeout(changeTimer);
    // A change is unsaved at once, so Submit and leaving the page never
    // miss it; whether the text is back to the stored text is worked out
    // when typing pauses.
    if (st.view === "rich") markUnsaved();
    const run = () => {
      if (cur !== st) return;
      paintDirty(st);
      syncUnsaved();
      if (st.checkBox) paintCheck(st);
    };
    if (st.view === "rich") changeTimer = setTimeout(run, 120);
    else run();
    queueDraft(st);
  }

  // Mount `kind` on `text` in place of the open view (or of the rendered
  // text, on opening). Source needs its bundle loaded first.
  function mountView(st, kind, text) {
    let handle;
    if (kind === "rich") {
      const R = window.AnnotateRich;
      const box = document.createElement("div");
      const format = R.formatOf(text);
      const h = R.mount(box, {
        text, format,
        onChange: () => changed(st),
        onSave: () => save(st),
        onDone: () => done(st),
        // Fenced code is painted by the page only in a markdown section.
        paintCode: format === "md" ? paintCode : undefined,
      });
      h.onLinkRequest = () => askLink(st);
      const el = box.firstElementChild;
      el.classList.add("ed-host");
      h.view.dom.setAttribute("aria-label", "Part text");
      handle = richHandle(h, el);
    } else {
      const el = document.createElement("div");
      el.className = "ed-host ed-cm ed-cm--source";
      const src = document.createElement("div");
      src.className = "ed-src";
      el.appendChild(src);
      // In the page before CodeMirror measures anything.
      placeHost(st, el);
      const h = window.AnnotateEditor.mount(src, {
        doc: text,
        onSave: () => save(st),
        onDone: () => done(st),
        onToggleMode: () => toggleView(st),
        onChange: () => changed(st),
      });
      // CodeMirror's textbox has no name of its own.
      h.view.contentDOM.setAttribute("aria-label", "Part text (markdown)");
      handle = sourceHandle(h, el);
    }
    const old = st.handle;
    placeHost(st, handle.el);
    st.handle = handle;
    st.host = handle.el;
    st.view = kind;
    if (old) {
      try { old.destroy(); } catch (_) {}
      old.el.remove();
    }
  }

  // The view's element goes where the rendered text is: right after it, in
  // the block body's flow (or after the view it replaces).
  function placeHost(st, el) {
    if (el.isConnected) return;
    if (st.host && st.host.isConnected) { st.host.insertAdjacentElement("afterend", el); return; }
    const content = st.section.querySelector(".block-content");
    const blockBody = st.section.querySelector(".block-body");
    if (content) content.insertAdjacentElement("afterend", el);
    else (blockBody || st.section).appendChild(el);
  }

  // The caret in Source at the place it was in Rich: the shortest start of
  // the text whose rendering holds as many visible characters as the Rich
  // document before the caret. Lands in the same block, close to the same
  // word (an unclosed `**` in a prefix reads as two more characters).
  const visible = (t) => t.replace(/\s+/g, "").length;
  function sourceOffsetFromRich(st, text) {
    try {
      const v = st.handle.view;
      const want = visible(v.state.doc.textBetween(0, v.state.selection.from, "\n", "\n"));
      if (!want) return 0;
      let lo = 0, hi = text.length;
      while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (visible(rendered(text.slice(0, mid))) >= want) hi = mid; else lo = mid + 1;
      }
      return lo;
    } catch (_) { return 0; }
  }

  // The caret in Rich at the Source caret: the rendered length of the text
  // before it.
  function renderedOffsetFromSource(st, text) {
    try {
      const head = st.handle.view.state.selection.main.head;
      return rendered(text.slice(0, head)).length;
    } catch (_) { return 0; }
  }

  // Flip to `kind`, carrying the text. Source → Rich asks first whether
  // Rich can show the text, and stays in Source with the reason if not.
  async function setView(st, kind) {
    if (cur !== st || st.switching || kind === st.view) return kind === st.view;
    if (st.phase !== "edit") return false;
    const text = st.handle.getText();
    let at = 0;
    if (kind === "rich") {
      const why = richRefusal(st, text);
      if (why) { say(st.richNote && !window.AnnotateRich ? st.richNote : `Rich editing isn't available — ${why}`); return false; }
      at = renderedOffsetFromSource(st, text);
    } else {
      at = sourceOffsetFromRich(st, text);
    }
    st.switching = true;
    try {
      if (kind === "source") {
        try { await loadEditor(); } catch (e) { say(e.message); return false; }
        if (cur !== st) return false;
      }
      st.linking = null;
      mountView(st, kind, text);
      if (kind === "rich") st.richNote = null;
    } finally {
      st.switching = false;
    }
    paintBar(st);
    if (kind === "rich") st.handle.focusAt(at);
    else placeCursor(st, at);
    return true;
  }
  const toggleView = (st) => setView(st, st.view === "rich" ? "source" : "rich");

  // A restored draft replaces the view's text; Rich is mounted afresh on
  // it (its own format), or Source shows it when Rich cannot.
  async function restoreText(st, text) {
    if (st.view === "source") { st.handle.setText(text); return; }
    if (!richRefusal(st, text)) { mountView(st, "rich", text); changed(st); return; }
    try { await loadEditor(); } catch (e) { say(e.message); return; }
    mountView(st, "source", text);
    st.richNote = NO_RICH;
    changed(st);
  }

  // ── What will be saved ──────────────────────────────────────────────────
  // The stored text against the text a save would send, word by word: Rich
  // writes bytes the reader cannot see (a block written fresh), and this is
  // where they are shown before they are stored.
  function toggleCheck(st) {
    if (st.checkBox) {
      st.checkBox.remove();
      st.checkBox = null;
    } else {
      st.checkBox = document.createElement("div");
      st.checkBox.className = "ed-diff ed-check";
      st.host.insertAdjacentElement("beforebegin", st.checkBox);
      paintCheck(st);
    }
    paintBar(st);
  }
  function paintCheck(st) {
    const box = st.checkBox;
    box.textContent = "";
    const k = document.createElement("div");
    k.className = "ed-split-k";
    k.textContent = "Stored → what will be saved";
    const body = document.createElement("div");
    body.className = "ed-diff-body";
    const text = st.handle.getText();
    if (text === st.body.markdown) {
      body.classList.add("ed-diff-none");
      body.textContent = "Nothing has changed.";
    } else {
      for (const p of window.AnnotateEditDiff.wordDiff(st.body.markdown, text)) {
        const el = p.op === "eq" ? document.createTextNode(p.text) : document.createElement(p.op);
        if (p.op !== "eq") el.textContent = p.text;
        body.appendChild(el);
      }
    }
    box.append(k, body);
  }

  // ── opening ─────────────────────────────────────────────────────────────
  async function open(blockId, opts) {
    opts = opts || {};
    if (readOnly() || busyOpening) return false;
    const section = sectionFor(blockId);
    if (cur && cur.blockId === blockId && cur.section === section) {
      if (opts.cursorAt) placeAt(cur, opts.cursorAt);
      else v_focus(cur);
      return true;
    }
    const why = refusal(section);
    if (why) { say(why); return false; }
    busyOpening = true;
    try {
      // One open at a time: the first is saved and closed. If it will not
      // save, it stays open with its reason, and the second does not open.
      if (cur && !(await done(cur))) {
        say("Finish the part you are editing first");
        return false;
      }
      // Rich is the default view; when its bundle cannot load, the editor
      // opens in Source and says so.
      let richNote = null;
      try { await loadRich(); } catch (e) { richNote = e.message; }
      // Held before it is read, so the text the editor opens on is text
      // Claude's pushes can no longer replace. A hold that cannot be written
      // (the daemon refused it) does not stop the edit: the save's If-Match
      // still refuses to overwrite a newer version.
      const openedAt = now();
      const held = await hold(blockId, openedAt);
      if (held === "refused") { say("Being edited in another tab"); return false; }
      let ok = false;
      try {
        let r;
        try { r = await request("GET", itemPath(blockId)); }
        catch (e) { say(`This section could not be opened (${e.message})`); return false; }
        if (!r.ok || !r.json || !r.json.body) { say(`This section could not be opened (${r.status})`); return false; }
        const md = typeof r.json.body.markdown === "string" ? r.json.body.markdown : "";
        let view = "rich";
        if (richNote) view = "source";
        else if (richRefusal({}, md)) { view = "source"; richNote = NO_RICH; }
        if (view === "source") {
          try { await loadEditor(); } catch (e) { say(e.message); return false; }
        }
        // The page may have moved on while the bundles and the block loaded.
        const live = sectionFor(blockId);
        const again = refusal(live);
        if (again) { say(again); return false; }
        mount(live, blockId, r.json, opts, view, richNote);
        cur.openedAt = openedAt;
        startHeartbeat(cur);
        ok = true;
        return true;
      } finally {
        if (!ok && held === "ok") release(blockId);
      }
    } finally {
      busyOpening = false;
    }
  }

  function mount(section, blockId, item, opts, view, richNote) {
    const body = Object.assign({}, item.body);
    if (typeof body.markdown !== "string") body.markdown = "";
    const st = {
      blockId, section, body, version: item.version, code: item.code,
      view, richNote, phase: "edit", diffShown: false, theirs: null,
      handle: null, host: null, checkBox: null, linking: null,
      // What the reader's words are measured against: the text and `mine`
      // the editor opened on, then each save of theirs. Keep mine adopts
      // Claude's body for its other fields, never as this base, or Claude's
      // words would be frozen as the reader's.
      mineBase: { markdown: body.markdown, mine: body.mine },
    };
    // Where the chosen words are in the rendered text, read while it shows.
    const at = renderedAt(section, opts.cursorAt);
    st.bar = document.createElement("div");
    st.bar.className = "ed-bar";
    const blockBody = section.querySelector(".block-body");
    (blockBody || section).insertAdjacentElement(blockBody ? "beforebegin" : "afterbegin", st.bar);

    cur = st;
    mountView(st, view, body.markdown);
    section.dataset.editing = "";
    delete section._pendingBlock;
    const draft = readDraft(st);
    if (draft !== null && draft !== body.markdown) st.phase = "draft";
    else if (draft !== null) clearDraft(st);
    paintBar(st);
    if (view === "rich") st.handle.focusAt(at);
    else placeCursor(st, opts.cursorAt ? offsetFor(body.markdown, opts.cursorAt) : 0);
  }

  // The start of the anchor's words in the section's rendered text (what
  // Rich's focusAt counts), or 0.
  function renderedAt(section, anchor) {
    const A = window.AnnotateAnchors;
    if (!anchor || !anchor.selected_text || !A) return 0;
    try {
      const root = A.contentOf(section);
      const hit = root && A.locateText(A.textOf(root), anchor, 0);
      return hit ? hit[0] : 0;
    } catch (_) { return 0; }
  }

  // An open editor asked to go to the chosen words.
  function placeAt(st, anchor) {
    if (st.view === "rich") st.handle.focusAt(renderedAt(st.section, anchor));
    else placeCursor(st, offsetFor(st.handle.getText(), anchor));
  }

  // The handle's focusAt centres the cursor, which scrolls the page: opening
  // must move nothing, and the words the reader chose are already in view.
  // Same CRLF arithmetic as focusAt: a two-byte separator is one position.
  function placeCursor(st, offset) {
    const view = st.handle.view;
    const text = st.handle.getText();
    const sep = text.includes("\r\n") ? "\r\n" : null;
    let pos = Math.max(0, offset | 0);
    if (sep) pos -= text.slice(0, pos).split(sep).length - 1;
    pos = Math.min(pos, view.state.doc.length);
    view.dispatch({ selection: { anchor: pos } });
    view.contentDOM.focus({ preventScroll: true });
  }

  // ── your words: `mine` ──────────────────────────────────────────────────
  // What the reader wrote is final, and Claude keeps it verbatim. So every
  // save records which words are theirs, as text anchors over the RENDERED
  // prose (the text AnnotateAnchors reads), not over the markdown: the diff
  // runs on the markdown, and each changed run is found again, without its
  // markers, in a detached render of the saved text.
  const CONTEXT = 32;

  function rendered(md) {
    const c = document.createElement("div");
    c.className = "block-content";
    c.innerHTML = window.AnnotatePage?.renderMarkdown ? window.AnnotatePage.renderMarkdown(md) : "";
    if (!window.AnnotatePage?.renderMarkdown) c.textContent = md;
    return window.AnnotateAnchors.textOf(c);
  }

  // A run's words as they read on the page: no `**`, backticks, `~~` or `_`
  // around a word, no `#`, `>` or list bullet opening a line, a link's text
  // without its target. A run that is only markers yields "", which is not
  // the reader's words (turning a line into a bullet wrote nothing).
  const LINE_MARK = /^[ \t]*(?:(?:#{1,6}|>|[-*+]|\d+[.)])(?:[ \t]+|$)|\[[ xX]\][ \t]+)+/;
  // Backslash escapes and HTML entities read as the characters they stand
  // for: `a\*b` is "a*b" on the page and `&amp;` is "&". The escaped
  // characters are set aside first, so a `\*` is never taken for emphasis.
  const ESC = 0xE000;
  let entityBox = null;
  function decodeEntities(s) {
    if (!/&[#\w]+;/.test(s)) return s;
    entityBox = entityBox || document.createElement("textarea");
    entityBox.innerHTML = s;
    return entityBox.value;
  }
  // An HTML tag is not words on the page (edit-diff.js's TAG).
  const TAG_RE = /<\/?[A-Za-z][\w:-]*(?:\s[^<>]*)?\/?>/g;
  function plain(text, atLineStart) {
    const kept = [];
    text = text.replace(TAG_RE, "");
    text = text.replace(/\\([!-\/:-@\[-`{-~])/g, (_, c) => String.fromCharCode(ESC + kept.push(c) - 1));
    const out = text.split(/(\r\n|\r|\n)/).map((line, i) => {
      if (i % 2) return line;
      if (i > 0 || atLineStart) line = line.replace(LINE_MARK, "");
      line = line.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1");
      return line.replace(/[^\s]+/g, (tok) => {
        if (/^[|:\-=*_~`#>+]+$/.test(tok)) return "";
        return tok.replace(/^[*_~`]+/, "").replace(/[*_~`]+(?=[^\w\s]*$)/, "");
      });
    }).join("");
    const back = out.replace(/[\uE000-\uF8FF]/g, (ch) => kept[ch.charCodeAt(0) - ESC] ?? ch);
    return decodeEntities(back);
  }

  function lineStartAt(md, i) {
    const nl = Math.max(md.lastIndexOf("\n", i - 1), md.lastIndexOf("\r", i - 1));
    return /^[ \t]*$/.test(md.slice(nl + 1, i));
  }

  // [start, end] in `aText` for the markdown slice md[start, end), or null.
  function findRun(md, aText, start, end) {
    const words = plain(md.slice(start, end), lineStartAt(md, start)).trim();
    if (!words) return null;
    const pre = plain(md.slice(Math.max(0, start - 200), start), lineStartAt(md, Math.max(0, start - 200)));
    const suf = plain(md.slice(end, end + 200), false);
    return window.AnnotateAnchors.locateText(aText, {
      selected_text: words, prefix: pre.slice(-CONTEXT), suffix: suf.slice(0, CONTEXT) }, 0, { words: true });
  }

  // Every span of the reader's in the saved text: the whole run when its
  // words read the same on the page, else line by line, else word by word
  // (a table row's pipes, a run that crosses a block boundary).
  function runSpans(md, aText, run) {
    const whole = findRun(md, aText, run.start, run.end);
    if (whole) return [whole];
    const out = [];
    const pieces = (re) => {
      const got = [];
      const slice = md.slice(run.start, run.end);
      for (let m; (m = re.exec(slice));) got.push([run.start + m.index, run.start + m.index + m[0].length]);
      return got;
    };
    const lines = pieces(/[^\r\n]+/g);
    for (const [s, e] of lines) {
      const hit = lines.length > 1 && findRun(md, aText, s, e);
      if (hit) { out.push(hit); continue; }
      for (const [ts, te] of pieces(/[^\s]+/g).filter(([ts]) => ts >= s && ts < e)) {
        const w = findRun(md, aText, ts, te);
        if (w) out.push(w);
      }
    }
    return out;
  }

  // Where words that read [s, e) in `bText` sit in `aText`, through the
  // words both share: the pieces of the span that survived the edit.
  function carry(bText, aText, s, e) {
    const out = [];
    let pb = 0, pa = 0;
    for (const op of window.AnnotateEditDiff.wordDiff(bText, aText)) {
      const n = op.text.length;
      if (op.op === "eq") {
        const lo = Math.max(s, pb), hi = Math.min(e, pb + n);
        if (lo < hi) out.push([pa + lo - pb, pa + hi - pb]);
        pb += n; pa += n;
      } else if (op.op === "del") pb += n;
      else pa += n;
    }
    return out;
  }

  // Where in `after` a change only re-formatted words: `long enough` made
  // `**long enough**` reads the same, and is not words the reader wrote.
  // Each change is the del/ins between two unchanged words, as changedRuns
  // groups them.
  const squash = (t) => t.replace(/\s+/g, " ").trim();
  function formattingOnly(before, after) {
    const out = [];
    let pa = 0, g = null;
    const close = () => {
      if (g && g.ins.trim() && squash(plain(g.del, g.delLine)) === squash(plain(g.ins, g.insLine))) {
        out.push([g.start, pa]);
      }
      g = null;
    };
    let pb = 0;
    for (const op of window.AnnotateEditDiff.wordDiff(before, after)) {
      if (op.op === "eq" && op.text.trim()) { close(); pa += op.text.length; pb += op.text.length; continue; }
      if (!g) g = { start: pa, del: "", ins: "", delLine: lineStartAt(before, pb), insLine: lineStartAt(after, pa) };
      if (op.op !== "ins") { g.del += op.text; pb += op.text.length; }
      if (op.op !== "del") { g.ins += op.text; pa += op.text.length; }
    }
    close();
    return out;
  }

  function computeMine(before, after, old) {
    if (!window.AnnotateAnchors || !window.AnnotateEditDiff) return Array.isArray(old) ? old : [];
    const aText = rendered(after);
    let spans = [];
    const same = formattingOnly(before, after);
    for (const run of window.AnnotateEditDiff.changedRuns(before, after)) {
      if (same.some(([s, e]) => s <= run.start && run.end <= e)) continue;
      spans.push(...runSpans(after, aText, run));
    }
    // Earlier words of the reader's are found where they were valid, in the
    // text before this edit, and carried through it: the parts the edit did
    // not touch stay theirs, and words the edit deleted stop being theirs.
    // Only an anchor that no longer reads in the text before (Claude moved
    // it) is looked for in the new text, and then only on whole words whose
    // surroundings still agree: marking words the reader did not write is
    // the failure to avoid.
    const prior = (Array.isArray(old) ? old : []).filter((a) => a && a.selected_text);
    let bText = null;
    for (const a of prior) {
      if (bText === null) bText = rendered(before);
      const was = window.AnnotateAnchors.locateText(bText, a, 0, { words: true });
      if (was) { spans.push(...carry(bText, aText, was[0], was[1])); continue; }
      const at = window.AnnotateAnchors.locateText(aText, a, 0, { words: true, context: true });
      if (at) spans.push(at);
    }
    // One anchor per stretch of the reader's words: overlaps, duplicates and
    // pieces with only whitespace between them are joined.
    spans = spans.map(([s, e]) => {
      while (s < e && /\s/.test(aText[s])) s++;
      while (e > s && /\s/.test(aText[e - 1])) e--;
      return [s, e];
    }).filter(([s, e]) => e > s).sort((x, y) => x[0] - y[0] || x[1] - y[1]);
    const merged = [];
    for (const sp of spans) {
      const last = merged[merged.length - 1];
      if (last && (sp[0] <= last[1] || !aText.slice(last[1], sp[0]).trim())) last[1] = Math.max(last[1], sp[1]);
      else merged.push(sp.slice());
    }
    return merged.map(([s, e]) => ({
      selected_text: aText.slice(s, e),
      prefix: aText.slice(Math.max(0, s - CONTEXT), s),
      suffix: aText.slice(e, e + CONTEXT),
    }));
  }

  // The green rule under the reader's words, and the title's badge, on every
  // section. An anchor Claude's rewrite took away (against the rule) is
  // simply not painted; one Claude moved is painted where it went.
  function paintMine() {
    const A = window.AnnotateAnchors;
    if (!A) return;
    const hl = A.supported() ? (CSS.highlights.get("annotate-mine") || new Highlight()) : null;
    if (hl) {
      hl.clear();
      hl.priority = -1;          // a mark the reader makes on them shows over it
      CSS.highlights.set("annotate-mine", hl);
    }
    for (const section of document.querySelectorAll("main.prose section.block[data-block-id]")) {
      let n = 0;
      for (const a of Array.isArray(section._mine) ? section._mine : []) {
        let r = null;
        try { r = A.rangeFor(section, a); } catch (_) { r = null; }
        if (!r) continue;
        n++;
        if (hl) hl.add(r);
      }
      if (n) section.dataset.mine = "";
      else delete section.dataset.mine;
    }
  }
  document.addEventListener("annotate:rendered", paintMine);
  // The blocks usually render before this file loads, and their
  // "annotate:rendered" has gone by: paint what is there now.
  paintMine();

  // ── saving ──────────────────────────────────────────────────────────────
  function payloadFor(st, text) {
    const mine = computeMine(st.mineBase.markdown, text, st.mineBase.mine);
    const out = Object.assign({}, st.body, { markdown: text });
    if (mine.length) out.mine = mine;
    else delete out.mine;
    return out;
  }

  // ⌘S keeps the editor open, but what is under it is now the saved text:
  // an export, or anything else that reads the card, sees what was saved.
  function renderHidden(st) {
    const c = st.section.querySelector(".block-content");
    if (!c || !window.AnnotatePage?.renderMarkdown) return;
    c.innerHTML = window.AnnotatePage.renderMarkdown(st.body.markdown);
    window.AnnotateGlossary?.decorate?.(c);
    st.section._mine = st.body.mine || [];
    paintMine();
  }

  // true when the section's stored text is now the editor's.
  async function save(st) {
    if (cur !== st || st.phase === "saving") return false;
    const text = st.handle.getText();
    if (text === st.body.markdown && !st.forceSave) return true;
    const payload = payloadFor(st, text);
    st.phase = "saving";
    paintBar(st);
    let r;
    try {
      r = await request("PUT", itemPath(st.blockId), payload, { "If-Match": String(st.version) });
    } catch (e) {
      return failSave(st, e.message || "the network request failed");
    }
    if (r.status === 412) {
      st.phase = "conflict";
      st.theirsVersion = r.json && r.json.version;
      st.theirs = null;
      paintBar(st);
      return false;
    }
    if (r.status === 404) {
      st.phase = "removed";
      paintBar(st);
      return false;
    }
    if (!r.ok) return failSave(st, (r.text || "").trim() || `HTTP ${r.status}`);
    const before = st.body.markdown;
    clearDraft(st);
    st.body = payload;
    st.mineBase = { markdown: text, mine: payload.mine };
    st.version = (r.json && r.json.version) || st.version + 1;
    st.saved = true;
    st.forceSave = false;
    st.phase = "edit";
    st.section.dataset.version = String(st.version);
    // The page wrote this text, so the change bar must not credit it to
    // Claude; and the round tells Claude exactly what the reader changed.
    window.AnnotatePage?.wrote?.(st.blockId, payload);
    window.AnnotateSubunits?.addEdit?.(st.blockId, before, text);
    renderHidden(st);
    paintBar(st);
    for (const fn of savedFns) {
      try { fn({ blockId: st.blockId, before, after: text, version: st.version, section: st.section }); }
      catch (e) { console.error(e); }
    }
    return true;
  }

  function failSave(st, reason) {
    st.phase = "error";
    st.error = reason;
    paintBar(st);
    return false;
  }

  async function done(st) {
    if (cur !== st) return true;
    if (st.phase === "removed") return false;
    if (st.phase === "conflict" || st.phase === "confirm") {
      // Esc in the prompt: it stays until the reader picks.
      return false;
    }
    if (!(await save(st))) return false;
    close(st);
    return true;
  }

  function discard(st) {
    clearDraft(st);
    close(st);
  }

  // ── closing ─────────────────────────────────────────────────────────────
  // `theirs`, when given, is the block the section shows instead of the
  // reader's (Take theirs).
  function close(st, theirs) {
    if (cur !== st) return;
    cur = null;
    clearTimeout(changeTimer);
    clearTimeout(draftTimer);
    clearInterval(st.beat);
    if (!st.released) release(st.blockId);
    syncUnsaved();
    const section = st.section;
    const hadFocus = st.host.contains(document.activeElement) || st.bar.contains(document.activeElement);
    try { st.handle.destroy(); } catch (_) {}
    st.bar.remove();
    st.host.remove();
    st.checkBox?.remove();
    st.diffBox?.remove();
    delete section.dataset.editing;
    const pending = section._pendingBlock;
    delete section._pendingBlock;
    if (section._removed) {
      section.remove();
      document.dispatchEvent(new CustomEvent("annotate:rendered"));
      return;
    }
    let live = section;
    const P = window.AnnotatePage;
    if (theirs && P?.renderBlock) {
      live = P.renderBlock(section, theirs, theirs.version);
      if (pending && pending.version > theirs.version) live = P.renderBlock(live, pending.block, pending.version);
    } else if (st.saved && P?.renderBlock) {
      const blk = Object.assign({}, st.body, { id: st.blockId, version: st.version });
      if (st.code !== undefined) blk.code = st.code;
      live = P.renderBlock(section, blk, st.version);
    }
    if (!theirs && pending && pending.version > st.version && P?.renderBlock) {
      live = P.renderBlock(live, pending.block, pending.version);
    }
    if (hadFocus) focusHome(live);
  }

  // ── the conflict ────────────────────────────────────────────────────────
  async function fetchTheirs(st) {
    if (st.theirs) return st.theirs;
    const r = await request("GET", itemPath(st.blockId));
    if (r.status === 404) { st.phase = "removed"; paintBar(st); return null; }
    if (!r.ok || !r.json) { failSave(st, `could not read the new version (${r.status})`); return null; }
    st.theirs = r.json;
    return st.theirs;
  }

  async function toggleDiff(st) {
    if (st.diffShown) {
      st.diffBox?.remove();
      st.diffBox = null;
      st.diffShown = false;
      paintBar(st);
      return;
    }
    const theirs = await fetchTheirs(st);
    if (!theirs || cur !== st) return;
    const parts = window.AnnotateEditDiff.wordDiff(
      (theirs.body && theirs.body.markdown) || "", st.handle.getText());
    const box = document.createElement("div");
    box.className = "ed-diff";
    const k = document.createElement("div");
    k.className = "ed-split-k";
    k.textContent = "Theirs → yours";
    const pre = document.createElement("div");
    pre.className = "ed-diff-body";
    for (const p of parts) {
      const el = p.op === "eq" ? document.createTextNode(p.text) : document.createElement(p.op);
      if (p.op !== "eq") el.textContent = p.text;
      pre.appendChild(el);
    }
    box.append(k, pre);
    // Beside the view, never inside it: Rich's element is the editor's own.
    (st.checkBox || st.host).insertAdjacentElement("beforebegin", box);
    st.diffBox = box;
    st.diffShown = true;
    paintBar(st);
  }

  async function takeTheirs(st) {
    const theirs = await fetchTheirs(st);
    if (!theirs || cur !== st) return;
    // Nothing of the reader's is stored: the section shows theirs. An
    // earlier ⌘S of this editor left an `edit` mark; the round's merge rule
    // drops it (theirs is where the reader started) or rewrites it to end
    // on theirs, never on words that are no longer on the page.
    clearDraft(st);
    if (st.saved) {
      const md = (theirs.body && typeof theirs.body.markdown === "string") ? theirs.body.markdown : "";
      window.AnnotateSubunits?.addEdit?.(st.blockId, st.body.markdown, md);
    }
    close(st, Object.assign({}, theirs.body, { id: st.blockId, version: theirs.version,
                                               code: theirs.code || theirs.body.code }));
  }

  async function keepMine(st) {
    const theirs = await fetchTheirs(st);
    if (!theirs || cur !== st) return;
    // Their other fields (a new title, a change note) are kept; only the
    // markdown is the reader's.
    st.body = Object.assign({}, theirs.body);
    if (typeof st.body.markdown !== "string") st.body.markdown = "";
    st.version = theirs.version;
    st.code = theirs.code;
    st.theirs = null;
    st.forceSave = true;
    st.phase = "edit";
    st.diffShown = false;
    st.diffBox?.remove();
    st.diffBox = null;
    await done(st);
  }

  // ── the section went away while open ────────────────────────────────────
  function removed(blockId) {
    if (!cur || cur.blockId !== blockId) return;
    cur.phase = "removed";
    paintBar(cur);
  }

  // Esc inside the editor is Done, and only Done: taken at the window in the
  // capture phase, ahead of maximize.js (which would close a maximised card
  // around the editor) and of everything else on the page.
  // A letter typed on one of the bar's buttons is not a page shortcut either:
  // `d` on Keep editing once marked the open section for deletion.
  // F6 is the way out of the text without leaving the editor: Tab indents
  // there, so it moves focus to the bar's first button, and back.
  // ⌘/ flips Rich and Source, from the text or the bar; taken here so
  // CodeMirror's own Mod-/ and the page never see it.
  window.addEventListener("keydown", (ev) => {
    if (!cur) return;
    const a = document.activeElement;
    if (!a || !(cur.host.contains(a) || cur.bar.contains(a))) return;
    // ⌘S on the bar (the link field, a button) saves, as it does in the text.
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && !ev.shiftKey && ev.key.toLowerCase() === "s"
        && cur.bar.contains(a)) {
      ev.preventDefault();
      ev.stopPropagation();
      save(cur);
      return;
    }
    if ((ev.metaKey || ev.ctrlKey) && !ev.altKey && !ev.shiftKey && ev.key === "/") {
      ev.preventDefault();
      ev.stopPropagation();
      const st = cur;
      toggleView(st).then((ok) => { if (ok && cur === st) v_focus(st); });
      return;
    }
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (ev.key === "F6") {
      ev.preventDefault();
      ev.stopPropagation();
      if (cur.bar.contains(a)) v_focus(cur);
      else cur.bar.querySelector("button:not([disabled])")?.focus({ preventScroll: true });
      return;
    }
    if (ev.key !== "Escape") {
      if (cur.bar.contains(a) && ev.key.length === 1 && ev.key !== " ") ev.stopPropagation();
      return;
    }
    ev.preventDefault();
    ev.stopPropagation();
    if (cur.linking && a.classList.contains("ed-link")) { cancelLink(cur); return; }
    if (cur.phase === "confirm") { cur.phase = "edit"; paintBar(cur); v_focus(cur); return; }
    done(cur);
  }, true);

  // ── the selection menu ──────────────────────────────────────────────────
  function addButton(t, menu) {
    if (readOnly() || !t || !t.section) return;
    if (NOT_TEXT.includes(t.section.dataset.kind || "markdown")) return;
    const sheet = menu.classList.contains("sel-sheet");
    const b = document.createElement("button");
    b.type = "button";
    b.dataset.act = "edit";
    b.innerHTML = ICON_EDIT + (sheet ? "<span>Edit</span>" : "");
    const why = refusal(t.section);
    b.title = why || "Edit — change the text yourself (e)";
    b.setAttribute("aria-label", b.title);
    if (why) b.disabled = true;
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const anchor = t.whole ? null : t.anchor;
      getSelection()?.removeAllRanges();
      window.AnnotateSelection.close();
      open(t.section.dataset.blockId, { cursorAt: anchor });
    });
    menu.appendChild(b);
  }
  if (window.AnnotateSelection) window.AnnotateSelection.registerAction(addButton);

  window.AnnotateEdit = {
    open,
    // This tab's name in `__holds__`.
    get tab() { return TAB; },
    // Tests: the heartbeat's interval, for editors opened after the call.
    setHeartbeatMs(ms) { heartbeatMs = Math.max(50, Number(ms) || 60000); },
    // Whether the open editor has words not yet saved.
    unsaved: () => unsaved,
    isOpen: (blockId) => !!cur && (blockId == null || cur.blockId === blockId),
    close: () => (cur ? done(cur) : Promise.resolve(true)),
    onSaved(fn) { if (typeof fn === "function") savedFns.push(fn); },
    // The open view's handle, or null: {kind: "rich" | "source", getText,
    // setText, focus, isFocused, focusAt, selectAll, view, …}.
    editor: () => (cur ? cur.handle : null),
    // The open view, "rich" or "source", or null.
    view: () => (cur ? cur.view : null),
    // Flip the open editor to "rich" or "source"; resolves to whether it did.
    setView: (kind) => (cur ? setView(cur, kind) : Promise.resolve(false)),
    removed,
    say,
    // Say why a section cannot be opened (the menu's `e` with no ✎ in it).
    sayWhy: (section) => { if (!readOnly()) say(refusal(section)); },
    paintMine,
    // A markdown run's words as the page shows them (the dock's edit row).
    plain: (text) => plain(text, true),
  };
})();
