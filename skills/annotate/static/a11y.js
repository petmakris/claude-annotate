// annotate skill — the parts of accessibility that watch the page rather than
// build it.
//
// The controls themselves get their names, roles and tab order where they are
// made (selection.js, subunits.js, script.js). What lives here is behaviour
// that has to see the page as a whole: saying out loud what just changed, and
// a key that reaches Submit from anywhere.
//
// It only ever reads the DOM the other modules build, and writes nothing but
// the status region. It never touches the round, the drafts or the lock — so it can be
// loaded, or dropped, without either of those modules knowing.
(function () {
  const status = document.getElementById("a11y-status");

  // ── Saying what changed ─────────────────────────────────────────────────
  // One polite status region for the whole page. Marking a sentence, adding
  // a comment and the round's count changing were all silent: the only live
  // regions were three hidden menu spans.
  let lastExplicit = 0;
  function say(msg) {
    if (!status) return;
    // Cleared first, then set on the next frame, so saying the same thing
    // twice ("1 mark in the round", undo, redo) is announced twice.
    status.textContent = "";
    requestAnimationFrame(() => { status.textContent = msg; });
  }
  function announce(msg) {
    lastExplicit = Date.now();
    say(msg);
  }

  // The round's size, read off the dock. Watched rather than reported by
  // subunits.js so the round's code carries no accessibility plumbing: the
  // dock is rebuilt on every change, and its rows are the count.
  let lastCount = 0;
  function countNow() {
    const dock = document.getElementById("round-dock");
    return dock ? dock.querySelectorAll(".rd-row").length : 0;
  }
  function onRoundChange() {
    const n = countNow();
    if (n === lastCount) return;
    lastCount = n;
    // A control that announced its own result a moment ago ("Comment added
    // to the round") has already said the useful thing.
    if (Date.now() - lastExplicit < 600) return;
    say(n === 0 ? "Nothing in the round"
      : `${n} mark${n === 1 ? "" : "s"} in the round`);
  }

  // The dock is replaced on every mark and sections on every rewrite, so
  // mutations arrive in bursts: one observer, coalesced to a frame.
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      onRoundChange();
    });
  }).observe(document.body, { subtree: true, childList: true });

  // ── `s` reaches Submit ───────────────────────────────────────────────────
  // The dock is fixed to the bottom of the screen but sits at the END of the
  // document, so reaching Submit by Tab took 616 presses on a 40-block page.
  function typing() {
    const a = document.activeElement;
    return a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement
      || (a && a.isContentEditable);
  }
  document.addEventListener("keydown", (ev) => {
    if (ev.key !== "s" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (typing()) return;
    const submit = document.getElementById("round-submit");
    ev.preventDefault();
    if (!submit) { announce("Nothing in the round yet"); return; }
    if (!submit.disabled) { submit.focus(); return; }
    // A disabled button cannot take focus; its label says why it is disabled
    // ("Finish or discard the open comment", "Claude is working…"), so go to
    // the drawer's toggle and read that label out instead.
    document.querySelector("#round-dock .rd-toggle")?.focus();
    announce(submit.textContent || "Submit is not available right now");
  });

  window.AnnotateA11y = { announce };
})();
