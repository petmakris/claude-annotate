// Bridges annotate's page code onto the webcompanion daemon.
//
// script.js was written against annotate's own server, which served the whole
// document from one route and answered "anything new?" once a second. The
// daemon serves one named item at a time and pushes changes as they happen.
// Rather than rewrite 129 KB of page code, this file re-creates the old
// window.WebCompanion surface on top of the new one:
//
//   api.fetchJSON("raw")        -> assembled from __doc__ + one GET per block
//   api.fetchJSON("prev")       -> the __prev__ item push.py wrote
//   init({onPollDelta})         -> per-anchor deltas folded into a version map
//
// Everything else — submit, finish, cancel, pasteImage, the write token, the
// read-only badge — is already identical on both sides and passes straight
// through.
(function () {
  const daemon = window.WebCompanion;
  if (!daemon) {
    console.error("annotate: webcompanion core.js did not load");
    return;
  }

  const BASE = (() => {
    const p = window.location.pathname;
    return p.endsWith("/") ? p : p + "/";
  })();

  // The daemon's core.js already owns the token, so borrow its fetch rather
  // than re-reading the URL fragment and getting a second, drifting copy.
  const rawGet = (path) => daemon.api.fetchJSON(path);

  const DOC = "__doc__";
  const PREV = "__prev__";
  const PROGRESS = "__progress__";
  const HOLDS = "__holds__";

  // ── Assembling the old /raw payload ──────────────────────────────────
  //
  // One GET per block looks profligate next to a single /raw, but it is what
  // buys fresh code anchors: the daemon resolves an item's anchors on every
  // read of that item, so a page left open all afternoon shows the file as it
  // is now, not as it was at push time. The per-item route is the only one
  // that resolves them at all.
  async function fetchRaw() {
    const snapshot = await rawGet("items");
    const doc = (snapshot[DOC] && snapshot[DOC].body) || {};
    const order = Array.isArray(doc.order) ? doc.order : [];
    const ids = order.filter((id) => Object.prototype.hasOwnProperty.call(snapshot, id));
    // Anything stored but not named in `order` still renders, after the
    // ordered run — a block the daemon has and the page refuses to show
    // would be invisible in a way nothing on the page could explain.
    for (const id of Object.keys(snapshot)) {
      if (!id.startsWith("__") && !ids.includes(id)) ids.push(id);
    }
    const blocks = await Promise.all(ids.map(async (id) => {
      const env = snapshot[id];
      try {
        const one = await rawGet("items/" + encodeURIComponent(id));
        // Body and version from the snapshot, which reads them as one pair;
        // only the resolved code anchors from this read. The daemon's
        // per-item route reads the body and derives the version in two
        // steps, so a write landing between them paired the NEW version with
        // the OLD body. The page stamped stale text as current, and the
        // delta that should have repainted it had already been spent.
        const body = (env && env.body) || one.body;
        return Object.assign({}, body, {
          version: (env && env.version) || one.version,
          code: one.code || (body && body.code) || undefined,
        });
      } catch (e) {
        // A single unreadable item costs its own card, never the page.
        return Object.assign({}, env && env.body, { version: (env && env.version) || 1 });
      }
    }));
    return {
      response_id: doc.response_id || "",
      title: doc.title || "",
      blocks: blocks.filter(Boolean),
      glossary: Array.isArray(doc.glossary) ? doc.glossary : [],
    };
  }

  async function fetchPrev() {
    try {
      const one = await rawGet("items/" + PREV);
      const body = one.body || {};
      const out = {};
      for (const [anchor, blk] of Object.entries(body)) {
        if (anchor.startsWith("__")) continue;
        if (blk && typeof blk.markdown === "string") out[anchor] = blk.markdown;
      }
      return { ok: true, blocks: out };
    } catch (_) {
      return { ok: false, blocks: {} };
    }
  }

  const api = {
    BASE,
    get writable() { return daemon.writable; },
    async fetchJSON(path, opts) {
      if (path === "raw") return await fetchRaw();
      if (path === "prev") return await fetchPrev();
      if (path.startsWith("raw?block=")) {
        const id = decodeURIComponent(path.split("raw?block=")[1].split("&")[0]);
        const one = await rawGet("items/" + encodeURIComponent(id));
        return Object.assign({}, one.body, { version: one.version, code: one.code });
      }
      return await daemon.api.fetchJSON(path, opts);
    },
    fetchText: (p) => daemon.api.fetchText(p),
    // ── Submit, and the one place the two models genuinely disagree ────
    //
    // The page sends three shapes: a whole round of content feedback
    // ({type:"round", reactions:[...]}), a choice pick (with
    // selected_options), and a plain comment. The daemon's submit route
    // stores exactly {anchor, text, images} and drops every other key —
    // deliberately, since it is not supposed to understand any client's
    // vocabulary.
    //
    // So the structure travels inside `text`, as JSON, always — never
    // sometimes-JSON-sometimes-prose, because a reader that has to guess
    // which it got is a bug waiting for the first comment containing a
    // brace. The anchor stays meaningful regardless, so a thread still keys
    // to the region the user was looking at.
    submit(payload) {
      const p = payload || {};
      const type = p.type || "comment";
      let anchor = p.anchor;
      if (!anchor) {
        if (type === "round") {
          // A round spans blocks, so it has no one region to key to. First
          // reaction's block is the closest honest answer for thread
          // placement; the reactions list inside carries the real scope.
          const first = (p.reactions || [])[0] || {};
          anchor = first.block_id || "__general__";
          if (first.step_id) anchor += "#" + first.step_id;
        } else {
          anchor = p.block_id || "__general__";
          if (p.step_id) anchor += "#" + p.step_id;
        }
      }
      const envelope = { type };
      if (type === "round") envelope.reactions = p.reactions || [];
      if (type === "choice") envelope.selected_options = p.selected_options || [];
      if (p.block_id) envelope.block_id = p.block_id;
      if (p.step_id) envelope.step_id = p.step_id;
      if (p.selected_text) envelope.selected_text = p.selected_text;
      envelope.text = p.text || "";
      const sending = daemon.api.submit({
        anchor,
        text: JSON.stringify(envelope),
        images: p.images || [],
      });
      // Locked from the moment the daemon has the event, until it is
      // answered; see the page lock below. It errs toward locked: an unlock
      // that never comes is visible and recoverable, a page that accepts a
      // second round while the first is in flight is neither.
      sending.then((res) => { if (res && res.event_id) hold(res.event_id); })
        .catch(() => {});
      return sending;
    },
    finish: () => daemon.api.finish(),
    cancel: () => daemon.api.cancel(),
    pasteImage: (b) => daemon.api.pasteImage(b),
  };

  // ── The old poll-delta shape ─────────────────────────────────────────
  //
  // script.js diffs two maps of {id: version} and re-renders what moved. The
  // daemon reports one anchor at a time, so accumulate its deltas into the
  // map script.js expects and hand it the same before/after pair it always
  // got. `initial` frames are the daemon replaying what a client could
  // already see from its own first read, so they seed the map without
  // triggering a re-render.
  let versions = {};

  // ── The page lock, reconstructed client-side ─────────────────────────
  //
  // The old server answered /poll with `busy: true` from the moment a
  // comment was queued until Claude wrote its ack, and the page rendered
  // that as a banner and a lock. The daemon keeps no such flag, so the page
  // keeps the set of events it has sent and not yet seen answered.
  //
  // The set lives in localStorage, keyed by the session's URL, not in a
  // variable. A variable died with a reload, which handed back an armed
  // Submit for a round already queued, and it was invisible to a second tab
  // on the same page, which could send the same round again.
  //
  // An event leaves the set when it is answered, and only then:
  //   - an `event-acked` delta naming it (the stream, or the daemon's poll
  //     fallback, both deliver these);
  //   - `acked` in /poll, read by the watch below. It lists every answered
  //     id, so it is what a reloaded page can still learn from;
  //   - the narration trail closing on that event id, which is Claude saying
  //     it is done, one step before the ack.
  // A block write is NOT an answer: Claude writes blocks while it works, and
  // unlocking on the first one re-armed Submit mid-round. That fallback is
  // kept only for a daemon too old to report acks at all, which /poll
  // reveals by having no `acked` field.
  const LOCK_KEY = "annotate.inflight." + BASE;
  // Answers that arrived before the submit that asked for them resolved.
  const answered = new Set();
  let inflight = readInflight();
  let onPollDeltaHandler = () => {};
  // null until the first /poll answers; then whether this daemon reports acks.
  let acksReported = null;
  let watcherAge = null;
  let finished = false;
  let watchTimer = null;
  const WATCH_EVERY_MS = 3000;

  function readInflight() {
    try {
      const v = JSON.parse(localStorage.getItem(LOCK_KEY) || "{}");
      return v && typeof v === "object" && !Array.isArray(v) ? v : {};
    } catch (_) { return {}; }
  }

  function writeInflight() {
    try {
      if (Object.keys(inflight).length) localStorage.setItem(LOCK_KEY, JSON.stringify(inflight));
      else localStorage.removeItem(LOCK_KEY);
    } catch (_) { /* private mode: the lock still holds for this tab */ }
  }

  const isBusy = () => !finished && Object.keys(inflight).length > 0;

  function hold(eventId) {
    const id = String(eventId);
    if (answered.has(id)) return;
    inflight[id] = Date.now();
    writeInflight();
    report([]);
    watch();
  }

  function release(ids) {
    const gone = [];
    for (const raw of ids) {
      const id = String(raw);
      if (id in inflight) { delete inflight[id]; gone.push(id); }
      else answered.add(id);
    }
    if (!gone.length) return;
    writeInflight();
    report(gone);
  }

  function blockVersions() {
    const blocks = {};
    const threads = {};
    for (const [k, v] of Object.entries(versions)) {
      if (k.startsWith("thread:")) threads[k.slice(7)] = v;
      else if (!k.startsWith("__")) blocks[k] = v;
    }
    return { blocks, threads };
  }

  // The shape script.js's onPollDelta was written against. `consumed_events`
  // carries the ids answered since the last report, which is what clears the
  // round, the general box's status line and the change bar.
  function snapshot(consumed) {
    const { blocks, threads } = blockVersions();
    const busy = isBusy();
    return {
      finished, busy, consumed_events: consumed, blocks, threads,
      // Only while something is waiting on the watcher: an idle page with no
      // Claude session behind it is not a page whose submission is stuck.
      watcher_age_s: busy ? watcherAge : null,
    };
  }

  function report(consumed) {
    const busy = isBusy();
    document.body.classList.toggle("is-busy", busy);
    document.dispatchEvent(new CustomEvent("annotate:busy",
                                           { detail: { busy, consumed } }));
    onPollDeltaHandler(snapshot(consumed), Object.assign({}, blockVersions().blocks));
  }

  // While something is in flight, ask /poll every few seconds whether it was
  // answered and whether the watcher that would answer it is still alive.
  // Straight to the network, past the route table below, which has nothing to
  // say about /poll.
  async function checkPoll() {
    let data;
    let serverNow = Date.now() / 1000;
    try {
      const r = await realFetch(BASE + "poll", { cache: "no-store" });
      if (!r.ok) return;
      data = await r.json();
      // The watcher's heartbeat is stamped by the daemon's clock. A phone's
      // clock is not the daemon's, so the age is measured against the
      // response's own Date header when there is one.
      const d = Date.parse(r.headers.get("Date") || "");
      if (!Number.isNaN(d)) serverNow = d / 1000;
    } catch (_) { return; }
    acksReported = Array.isArray(data.acked);
    if (data.finished || data.cancelled) finished = true;
    const before = watcherAge;
    watcherAge = typeof data.watcher_seen_at === "number"
      ? Math.max(0, serverNow - data.watcher_seen_at) : null;
    const answeredNow = acksReported
      ? data.acked.map(String).filter((id) => id in inflight) : [];
    if (answeredNow.length) release(answeredNow);
    else if (finished || (before === null) !== (watcherAge === null)
             || Math.floor((before || 0) / 5) !== Math.floor((watcherAge || 0) / 5)) {
      report([]);
    }
    if (!isBusy()) stopWatch();
  }

  function watch() {
    if (watchTimer || !isBusy()) return;
    watchTimer = setInterval(checkPoll, WATCH_EVERY_MS);
    checkPoll();
  }

  function stopWatch() {
    if (watchTimer) { clearInterval(watchTimer); watchTimer = null; }
  }

  // Claude closes the trail on an event just before acking it. Unlike an ack
  // that fired while this page was closed, the trail can still be read.
  async function checkTrail() {
    if (!isBusy()) return;
    try {
      const one = await rawGet("items/" + PROGRESS);
      const body = (one && one.body) || {};
      if (body.state === "done" && body.event_id) release([String(body.event_id)]);
    } catch (_) { /* no trail yet */ }
  }

  // Another tab sent, or saw answered, something on this same page.
  window.addEventListener("storage", (e) => {
    if (e.key !== LOCK_KEY) return;
    const next = readInflight();
    const gone = Object.keys(inflight).filter((id) => !(id in next));
    const changed = gone.length || Object.keys(next).some((id) => !(id in inflight));
    inflight = next;
    if (changed) report(gone);
    if (isBusy()) watch(); else stopWatch();
  });

  function toOldShape(handler) {
    onPollDeltaHandler = handler;
    return function onDelta(ev) {
      if (!ev) return;
      // Carries no anchor, so it is handled before the anchor check below,
      // which used to drop every one of these.
      if (ev.kind === "event-acked") {
        if (ev.event_id != null) release([String(ev.event_id)]);
        return;
      }
      if (!ev.anchor) return;
      const key = ev.kind === "thread" ? "thread:" + ev.anchor : ev.anchor;
      const before = Object.assign({}, blockVersions().blocks);
      versions[key] = ev.version;
      if (ev.initial) return;
      if (ev.anchor === "__session__" || ev.ended) {
        document.body.classList.add("session-finished");
        return;
      }
      // A tab opening or closing an editor (edit.js) is not a block change,
      // and not Claude answering either: it must neither reconcile the page
      // nor unlock a round in flight.
      if (ev.anchor === HOLDS) {
        document.dispatchEvent(new CustomEvent("annotate:holds",
                                               { detail: { version: ev.version } }));
        return;
      }
      // The narration trail is written WHILE the page is locked, so it must
      // not be mistaken for the work finishing — unless it says it finished.
      if (ev.anchor === PROGRESS) {
        document.dispatchEvent(new CustomEvent("annotate:progress",
                                               { detail: { version: ev.version } }));
        checkTrail();
        return;
      }
      if (ev.kind === "item" && isBusy() && acksReported === false) {
        release(Object.keys(inflight));
        return;
      }
      handler(snapshot([]), before);
    };
  }

  // ── The same three routes, intercepted at the fetch layer ───────────
  //
  // Not every call site goes through api.fetchJSON: script.js reaches for
  // `fetch(BASE + "raw")` directly in two places, and export.js walks the
  // page's own <link> tags. Patching those call sites would work until the
  // next one is written, so the synthesis is installed where every caller
  // meets it instead — one route table, no second place to keep in step.
  const routes = {
    raw: fetchRaw,
    prev: fetchPrev,
  };

  const realFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const href = typeof input === "string" ? input : (input && input.url) || "";
    let path = href;
    try {
      path = new URL(href, window.location.href).pathname
        + (new URL(href, window.location.href).search || "");
    } catch (_) { /* keep the raw string */ }
    if (path.startsWith(BASE)) {
      const rest = path.slice(BASE.length);
      const name = rest.split("?")[0];
      if (name === "raw" && rest.includes("block=")) {
        const id = decodeURIComponent(rest.split("block=")[1].split("&")[0]);
        const one = await rawGet("items/" + encodeURIComponent(id));
        return jsonResponse(Object.assign({}, one.body,
                                          { version: one.version, code: one.code }));
      }
      if (Object.prototype.hasOwnProperty.call(routes, name)) {
        return jsonResponse(await routes[name]());
      }
    }
    return realFetch(input, init);
  };

  function jsonResponse(obj) {
    return new Response(JSON.stringify(obj), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }

  window.WebCompanion = {
    api,
    get writable() { return daemon.writable; },
    resolveWritable: () => daemon.resolveWritable(),
    init({ onPollDelta }) {
      daemon.init({ onDelta: toOldShape(onPollDelta || (() => {})) });
      // A round sent before a reload, or from another tab, is still in the
      // stored set: lock now, then find out whether it was answered meanwhile.
      if (isBusy()) { report([]); checkTrail(); }
      watch();
      // Learn whether this daemon reports acks, even with nothing in flight,
      // so the first block write of the next round is judged correctly.
      if (!isBusy()) checkPoll();
    },
    // Whether an event this page (or another tab) sent is still unanswered.
    isHeld: (eventId) => String(eventId) in inflight,
  };
})();
