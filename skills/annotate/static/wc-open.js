/* wc-open.js — "open this file in my editor", the one way every page asks.
 *
 * Canonical source: skills/_shared/static/wc-open.js. Each skill that uses it
 * carries a byte-identical copy in its own static/; skills/tests/
 * test_shared_static_copies.py fails on a copy that drifts. Edit the
 * canonical file, then copy it over.
 *
 * The page cannot open a file itself: file:// is refused from an http origin,
 * and jetbrains:// had to guess the project name. The daemon's POST /api/open
 * runs the opener instead. What comes back is the daemon's own reason when it
 * refuses, never a guess; how a failure is shown is the page's business.
 *
 *   WcOpen.open({file, line, key?}) -> Promise<{ok: true} | {ok: false, reason, unreachable?}>
 *
 * `key` is the session's slug or sid, for a `file` relative to that session's
 * workspace; without it `file` must be an absolute path inside one.
 */
(function () {
  "use strict";

  async function open(target) {
    const t = target || {};
    const body = { file: t.file, line: t.line };
    if (t.key != null) body.key = t.key;
    let res;
    try {
      res = await fetch("/api/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
    } catch (_) {
      return { ok: false, reason: "server unreachable", unreachable: true };
    }
    if (res.ok) return { ok: true };
    let reason = "";
    try { reason = await res.text(); } catch (_) { /* the status stands in */ }
    return { ok: false, reason: reason || "could not open" };
  }

  window.WcOpen = { open };
})();
