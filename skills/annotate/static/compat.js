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
//   api.fetchJSON("statusline") -> gone; answers {ok:false} so the strip hides
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
        return Object.assign({}, one.body, {
          version: one.version,
          code: one.code || (one.body && one.body.code) || undefined,
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
      // The live context readout is gone. It worked because annotate's own
      // server read a file off the disk on request; the daemon is deliberately
      // not allowed to read arbitrary paths, and that restraint is worth more
      // than the widget. {ok:false} is the same answer the old route gave when
      // no snapshot existed, so the strip stays hidden instead of erroring.
      if (path === "statusline") return { ok: false };
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
      // The daemon's /poll does not report whether an event is still
      // unacked, so the lock the old server drove from the server side is
      // driven from here instead. Optimistic, and it errs toward locked:
      // an unlock that never comes is visible and recoverable, a page that
      // accepts a second round while the first is in flight is neither.
      sending.then(() => setBusyLocal(true)).catch(() => {});
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
  // that as a banner and a lock. The daemon knows the same fact — the ack
  // is a file in the session's own workspace — but does not report it, so
  // there is nothing to read. Instead: lock on submit, and unlock when an
  // item actually changes, because annotate rewrites a block and only then
  // acks. The failure mode is an ack that rewrites nothing, which leaves
  // the banner up until the next change; that is the direction to fail in.
  let busyLocal = false;

  function setBusyLocal(v) {
    busyLocal = !!v;
    document.body.classList.toggle("is-busy", busyLocal);
    document.dispatchEvent(new CustomEvent("annotate:busy", { detail: busyLocal }));
  }

  function toOldShape(handler) {
    return function onDelta(ev) {
      if (!ev || !ev.anchor) return;
      const key = ev.kind === "thread" ? "thread:" + ev.anchor : ev.anchor;
      const before = Object.assign({}, versions);
      versions[key] = ev.version;
      if (ev.initial) return;
      if (ev.anchor === "__session__" || ev.ended) {
        document.body.classList.add("session-finished");
        return;
      }
      const blocks = {};
      const threads = {};
      for (const [k, v] of Object.entries(versions)) {
        if (k.startsWith("thread:")) threads[k.slice(7)] = v;
        else if (!k.startsWith("__")) blocks[k] = v;
      }
      if (ev.kind === "item" && busyLocal) setBusyLocal(false);
      handler({ finished: false, busy: busyLocal, consumed: [], blocks, threads }, before);
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
    statusline: async () => ({ ok: false }),
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
    },
  };
})();
