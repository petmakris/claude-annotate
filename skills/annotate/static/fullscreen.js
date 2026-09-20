// annotate — Full screen: hand the whole page to the browser's Fullscreen API.
//
// Desktop already has an escape from the surrounding chrome — F11 — that this
// page does nothing to provide or replace. A phone has no such key: Chrome and
// Firefox on Android keep their own address bar and system nav pinned above
// and below the page, with no menu item that hides them for a site that never
// asked. This button is that ask.
(function () {
  "use strict";

  const btn = document.getElementById("fullscreen-toggle");
  if (!btn) return;

  // Feature-detected once, synchronously, so there is no flash of a visible
  // button that then disappears — the same shape highlighter.js uses for the
  // Highlight API.
  if (!document.documentElement.requestFullscreen || !document.exitFullscreen) {
    btn.hidden = true;
    return;
  }

  const ICON_ENTER =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/>' +
    '<line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';
  const ICON_EXIT =
    '<svg viewBox="0 0 24 24" aria-hidden="true">' +
    '<polyline points="4 14 10 14 10 20"/><polyline points="20 10 14 10 14 4"/>' +
    '<line x1="14" y1="10" x2="21" y2="3"/><line x1="3" y1="21" x2="10" y2="14"/></svg>';

  function sync() {
    const on = !!document.fullscreenElement;
    btn.innerHTML = on ? ICON_EXIT : ICON_ENTER;
    btn.title = on ? "Exit full screen" : "Full screen — hide the browser chrome";
    btn.setAttribute("aria-label", btn.title);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
  }

  btn.addEventListener("click", () => {
    // Best-effort both ways: a rejected promise (permission policy, another
    // element already holding fullscreen) must not throw out of a click
    // handler, and must leave the button in whatever state actually resulted
    // — which the fullscreenchange listener below reports, not this call.
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else document.documentElement.requestFullscreen().catch(() => {});
  });

  // Covers every way out, not just this button: Esc, the browser's own exit
  // control, or another script (maximize.js) driving the same element.
  document.addEventListener("fullscreenchange", sync);
  sync();
})();
