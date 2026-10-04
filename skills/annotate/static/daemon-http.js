// skills/annotate/static/daemon-http.js
/* The headers every direct request to the daemon carries.
 *
 * Most of the page talks to the daemon through WebCompanion.api, whose
 * core.js adds these itself. Two files call fetch directly — edit.js, for
 * If-Match writes, and speech-client.js, for routes at the site root rather
 * than under the session — and each used to keep its own copy of the header
 * rules with a note to keep them in step with core.js. This is that copy,
 * once: the contract number, and the owner token from sessionStorage when the
 * page was opened through an owner URL.
 */
(function () {
  "use strict";

  const CONTRACT = "1";
  const TOKEN_KEY = "webcompanion.token." + location.host;

  function headers(extra) {
    const h = Object.assign({ "X-WebCompanion-Contract": CONTRACT }, extra || {});
    try { const t = sessionStorage.getItem(TOKEN_KEY); if (t) h["X-WebCompanion-Token"] = t; } catch (_) {}
    return h;
  }

  window.AnnotateDaemonHttp = { CONTRACT, TOKEN_KEY, headers };
})();
