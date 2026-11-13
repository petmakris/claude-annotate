// The narration panel — what Claude is doing, while the page waits.
//
// A reader comments on a block and Claude goes away for minutes. The page had
// a spinner and a ticking timer and nothing else: script.js's applyProgress
// has been receiving `undefined` since the daemon cutover, because compat.js's
// synthesised delta never carried a `progress` key, and the hook that used to
// produce labels went dormant in the same move.
//
// This is the reading half. compat.js re-broadcasts a `__progress__` item
// change as `annotate:progress` (it cannot reach script.js: compat.js:207
// strips `__`-prefixed anchors out of the version map), and this file re-reads
// the item and paints it.
(function () {
  "use strict";

  const ROUTE = "raw?block=__progress__";
  const PANEL_ID = "progress-panel";
  const FEED_ID = "progress-feed";

  // It floats in the bottom right, out of the page's flow, so it never moves
  // the text. At rest it is a pill (a spinner and the clock while Claude
  // works, how long it took once done); a click opens it into a card with
  // the trail. The reader's own choice of pill or card holds for the page.
  let openPref = null;
  // ✕ hides the trail until Claude's next round. A round is known by when it
  // started, kept per page so a reload does not bring a dismissed one back.
  const DISMISS_KEY = "annotate.progress.dismissed:" + location.pathname;
  function dismissedRound() {
    try { return localStorage.getItem(DISMISS_KEY); } catch (_) { return null; }
  }

  function writable() {
    const wc = window.WebCompanion;
    // Absent means the shim has not installed yet; treat as not writable and
    // let the next broadcast re-decide, rather than flashing the trail at a
    // guest for one frame.
    //
    // This gate decides whether the trail is DRAWN. It does not decide
    // whether the guest has it: the daemon's `GET /s/<sid>/items` is
    // unauthenticated and hands back every item including `__`-prefixed
    // anchors, and compat.js fetches that route on every page load, guest
    // included — so `__progress__` is already in this browser, and one
    // `curl` against the share link reads it. Withholding it would be a
    // `webcompanion` change, out of scope by spec decision 2. The real
    // containment is the contract rule that narration carries no output,
    // secrets or tokens (references/handling-events.md).
    return !!(wc && wc.writable);
  }

  function clock(secs) {
    const s = Math.max(0, Math.floor(secs));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function spoken(secs) {
    const s = Math.max(0, Math.floor(secs));
    if (s < 60) return s + " s";
    const m = Math.floor(s / 60);
    return m + " min " + (s % 60) + " s";
  }

  function remove() {
    const el = document.getElementById(PANEL_ID);
    if (el) el.remove();
  }

  function ensure() {
    let el = document.getElementById(PANEL_ID);
    if (el) return el;
    el = document.createElement("section");
    el.id = PANEL_ID;
    el.className = "pg-panel";
    const close = '<button type="button" class="pg-close" aria-label="Dismiss until Claude\'s next round"' +
        ' title="Dismiss until Claude\'s next round">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><line x1="6" y1="6" x2="18" y2="18"></line>' +
        '<line x1="18" y1="6" x2="6" y2="18"></line></svg></button>';
    // The live region is its own hidden line, not the pill or the card: only
    // one of those shows at a time, and a live region inside a hidden element
    // says nothing. It carries the CURRENT LINE only, atomically, so a
    // repaint never re-announces the whole trail. The feed is explicitly
    // `aria-live="off"` so it cannot inherit a live region later.
    el.innerHTML =
      '<span class="pg-live sr-only" role="status" aria-live="polite" aria-atomic="true"></span>' +
      '<div class="pg-pill-row">' +
        '<button type="button" class="pg-pill" aria-expanded="false" aria-controls="progress-card"' +
          ' title="Show what Claude has done">' +
          '<span class="pg-mark"></span><span class="pg-pill-text"></span>' +
          '<span class="pg-pill-meta"></span>' +
        '</button>' + close +
      '</div>' +
      '<div class="pg-card" id="progress-card">' +
        '<div class="pg-head">' +
          '<span class="pg-mark"></span>' +
          '<span class="pg-now"></span>' +
          '<span class="pg-count"></span>' +
          '<span class="pg-timer"></span>' +
          '<button type="button" class="pg-caret" aria-expanded="true"' +
            ' aria-controls="progress-card" aria-label="Fold into the pill" title="Fold into the pill">' +
            '<svg viewBox="0 0 24 24" aria-hidden="true">' +
            '<polyline points="6 9 12 15 18 9"></polyline></svg>' +
          '</button>' + close +
        '</div>' +
        '<div class="pg-feed" id="' + FEED_ID + '" aria-live="off"></div>' +
      '</div>';
    el.querySelector(".pg-pill").addEventListener("click", () => {
      openPref = true;
      paintOpen(el);
      el.querySelector(".pg-caret").focus();
    });
    el.querySelector(".pg-caret").addEventListener("click", () => {
      openPref = false;
      paintOpen(el);
      el.querySelector(".pg-pill").focus();
    });
    el.querySelectorAll(".pg-close").forEach((b) => b.addEventListener("click", () => {
      try { localStorage.setItem(DISMISS_KEY, el.dataset.startedAt || ""); } catch (_) {}
      el.hidden = true;
    }));
    // Floating, so it hangs off <body> and takes no room in the page.
    document.body.appendChild(el);
    return el;
  }

  // Write only on change. `textContent = x` replaces the text node even when
  // the string is identical, and a live region can announce that as new.
  function say(el, text) {
    if (el && el.textContent !== text) el.textContent = text;
  }

  function paintOpen(el) {
    const open = openPref === true;
    el.dataset.open = open ? "1" : "0";
    el.querySelector(".pg-pill").setAttribute("aria-expanded", open ? "true" : "false");
    el.querySelector(".pg-caret").setAttribute("aria-expanded", open ? "true" : "false");
  }

  function paint(body) {
    if (!body || !Array.isArray(body.steps) || !body.steps.length) { remove(); return; }
    if (!writable()) { remove(); return; }

    const el = ensure();
    const done = body.state === "done";
    el.dataset.state = done ? "done" : "working";

    const started = Number(body.started_at) || 0;
    const ended = Number(body.ended_at) || 0;
    const steps = body.steps;
    const last = steps[steps.length - 1];

    // The clock reads this rather than re-fetching the item every second.
    el.dataset.startedAt = String(started);

    // Dismissed for this round only: a new round has a new start.
    el.hidden = dismissedRound() === String(started);
    el.querySelectorAll(".pg-mark").forEach((m) => {
      m.className = "pg-mark " + (done ? "pg-tick" : "pg-spin");
      m.textContent = done ? "✓" : "";
    });
    const count = steps.length + (steps.length === 1 ? " step" : " steps");
    el.querySelector(".pg-count").textContent = count;
    if (done) {
      const summary = "Claude worked for " + spoken(ended - started) + " across " + count;
      say(el.querySelector(".pg-now"), summary);
      say(el.querySelector(".pg-live"), summary);
      say(el.querySelector(".pg-pill-text"), "Done in " + spoken(ended - started));
      el.querySelector(".pg-pill-meta").textContent = count;
      el.querySelector(".pg-count").textContent = "";
      el.querySelector(".pg-timer").textContent = "";
    } else {
      say(el.querySelector(".pg-now"), last ? last.text : "");
      say(el.querySelector(".pg-live"), last ? last.text : "");
      say(el.querySelector(".pg-pill-text"), "Claude is working");
      const t = clock((Date.now() / 1000) - started);
      el.querySelector(".pg-timer").textContent = t;
      el.querySelector(".pg-pill-meta").textContent = t;
    }
    const feed = document.getElementById(FEED_ID);
    feed.textContent = "";
    steps.forEach((s, i) => {
      const row = document.createElement("div");
      row.className = "pg-line" + (i === steps.length - 1 && !done ? " now" : "");
      const t = document.createElement("span");
      t.className = "t";
      t.textContent = clock((Number(s.t) || started) - started);
      const txt = document.createElement("span");
      // textContent, never innerHTML: this string is Claude's prose and the
      // page must not become a place where it can inject markup.
      txt.textContent = s.text;
      row.append(t, txt);
      feed.appendChild(row);
    });

    paintOpen(el);
    // Pin to the newest line. Without this the one line the reader most wants
    // — the current one — is the line clipped off the bottom, measured in the
    // mockup this design was chosen from.
    feed.scrollTop = feed.scrollHeight;

    // Deliberately NOT writing the current line into `.updating-label`.
    // There is one trail per event and it carries no block id, so the only
    // thing this file could do is write the same sentence into every
    // `.updating-label` on the page — a round touching five blocks then shows
    // the identical line on all five, which reads as five separate claims and
    // is wrong for at least four of them. The deleted `applyProgress` could
    // caption a specific block because its map was keyed per event and
    // resolved to one block; nothing in the progress item replaces that key.
    // Each block keeps script.js's own "updating" pill and its own timer, and
    // the panel above is the one place the current line belongs.
  }

  // The one local timer: the elapsed clock. It reads nothing from the daemon —
  // every LINE arrives on the stream. Started when a trail is working, stopped
  // the moment it is not, so a finished round leaves nothing ticking.
  let ticking = null;

  function tick() {
    const p = document.getElementById(PANEL_ID);
    if (!p || p.dataset.state !== "working") {
      clearInterval(ticking); ticking = null; return;
    }
    const t = clock((Date.now() / 1000) - Number(p.dataset.startedAt || 0));
    p.querySelector(".pg-timer").textContent = t;
    p.querySelector(".pg-pill-meta").textContent = t;
  }

  async function refresh() {
    if (!writable()) { remove(); return; }
    let body = null;
    try {
      // Not `window.WebCompanion.fetchJSON` — every other call site in this
      // codebase (script.js's WebCompanion.api.submit/.finish/.pasteImage)
      // reaches through `.api`, because that's the surface both core.js and
      // compat.js actually expose; `fetchJSON` was never promoted to the top
      // level. Calling it there is a TypeError that refresh()'s own catch
      // swallows, so the panel silently never painted, in any browser, at
      // any timing — caught by test_browser_review.py's load-time test.
      body = await window.WebCompanion.api.fetchJSON(ROUTE);
    } catch (_) {
      // No trail yet is the common case on a fresh page, and a failed read
      // must never be louder than the document it sits above.
      remove();
      return;
    }
    paint(body);
    const el = document.getElementById(PANEL_ID);
    if (el && el.dataset.state === "working" && !ticking) {
      ticking = setInterval(tick, 1000);
    }
  }

  // The load-time boot path, not the live-event path: core.js's write
  // capability probe (resolveWritable) is kicked off fire-and-forget by
  // script.js's WebCompanion.init() call a few lines before this file even
  // starts executing, but its fetch("/api/whoami") is never synchronous. If
  // it has not settled by the time this file's own first refresh() would
  // run, writable() reads false even for the session's OWNER, refresh()
  // removes/no-ops the panel — and for a page loaded onto an already-finished
  // trail, no annotate:progress event is ever coming to trigger a later
  // repaint (compat.js returns early for initial frames). So boot() awaits
  // the verdict once, before its first refresh(), rather than trusting
  // whatever writable() already happens to read.
  //
  // compat.js forwards resolveWritable bare — `() => daemon.resolveWritable()`
  // — with no de-duplication, so awaiting it here is a second, independent
  // call into core.js's resolveWritable(), which re-probes /api/whoami rather
  // than reusing script.js's already in-flight probe. The alternative
  // considered was a MutationObserver on document.body's `class` attribute,
  // which core.js's resolveWritable toggles `read-only` on the moment its
  // verdict lands (event-free, no extra fetch) — but DOMTokenList's
  // `toggle(token, force)` is a no-op that fires NO mutation at all when the
  // token is already absent and force is falsy, which is exactly an owner's
  // case: `read-only` starts absent, and toggling it with `!writable` false
  // never touches the attribute. That observer would never fire for the one
  // case this bug is about, only for guests, who never needed the signal. A
  // second, bounded, one-time fetch at boot is the honest cost of a signal
  // that actually reaches the owner.
  async function boot() {
    const wc = window.WebCompanion;
    if (wc && typeof wc.resolveWritable === "function") {
      try { await wc.resolveWritable(); } catch (_) { /* refresh() re-checks writable() itself */ }
    }
    refresh();
  }

  document.addEventListener("annotate:progress", refresh);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
