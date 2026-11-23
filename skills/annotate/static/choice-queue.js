// Choice queues. Adjacent choice blocks sharing a spec.group (script.js puts
// it on the section as data-group) show one question at a time, under a bar
// with progress and navigation. Every member stays an ordinary choice section
// rendered by renderChoice, so its answer, comments and rewrites are the ones
// any block has; the queue only decides which member is on screen.
//
// The bar is rebuilt from scratch after every render: reconcile() inserts new
// sections relative to their neighbours, and a bar left in place would end up
// on the wrong side of one.
(function () {
  "use strict";

  const HIDDEN = "cq-hidden";
  let searching = false;
  const at = {};            // run key -> block id of the current member

  const prose = () => document.querySelector("main.prose");
  const rid = () => document.body.dataset.responseId || "default";
  const skey = (run, what) => `annotate.queue:${rid()}:${run.key}:${what}`;
  function load(run, what) {
    try { return window.localStorage.getItem(skey(run, what)); } catch (_) { return null; }
  }
  function save(run, what, v) {
    try { window.localStorage.setItem(skey(run, what), v); } catch (_) {}
  }

  function decided(sec) {
    return !!window.AnnotateSubunits?.choiceMark(sec.dataset.blockId);
  }

  // Runs of two or more adjacent choice sections with equal data-group. Our
  // own bars sit between sections and do not break a run.
  function runs() {
    const root = prose();
    if (!root) return [];
    const out = [];
    let cur = null;
    for (const el of root.children) {
      if (el.classList.contains("cq-bar")) continue;
      const g = el.matches("section.block") && el.dataset.kind === "choice" ? el.dataset.group : "";
      if (g && cur && cur.group === g) cur.members.push(el);
      else if (g) { cur = { group: g, members: [el] }; out.push(cur); }
      else cur = null;
    }
    const queues = out.filter((r) => r.members.length > 1);
    queues.forEach((r) => { r.key = r.group + "|" + r.members[0].dataset.blockId; });
    return queues;
  }

  const expanded = (run) => searching || load(run, "all") === "1";
  const ids = (run) => run.members.map((m) => m.dataset.blockId);

  function currentIndex(run) {
    let i = ids(run).indexOf(at[run.key] || load(run, "at"));
    if (i < 0) {
      i = run.members.findIndex((m) => !decided(m));
      if (i < 0) i = 0;
      // Pin the fallback, or answering this question would make the "first
      // undecided" one the next, and the page would move without being asked.
      at[run.key] = ids(run)[i];
    }
    return i;
  }

  function setCurrent(run, i) {
    const id = run.members[i].dataset.blockId;
    at[run.key] = id;
    save(run, "at", id);
  }

  function setHidden(sec, hide) {
    sec.classList.toggle(HIDDEN, hide);
  }

  // The bar is deliberately small: a ring for progress, one line saying where
  // the reader is, and the three moves they make. It used to carry a progress
  // bar AND one dot per question, which said the same thing twice and turned
  // into a row of noise at sixty questions. Jumping to a particular question
  // is what Show all and search are for.
  function bar(run, i, all) {
    const n = run.members.length;
    const done = run.members.filter(decided).length;
    const r = 14, c = 2 * Math.PI * r;
    const open = nextUndecided(run, i);
    const el = document.createElement("div");
    el.className = "cq-bar";
    el.dataset.run = run.key;
    el.innerHTML =
      `<svg class="cq-ring" viewBox="0 0 34 34" role="img" aria-label="${done} of ${n} decided">` +
      `<circle class="cq-ring-track" cx="17" cy="17" r="${r}"/>` +
      // No fill at zero: a round-capped stroke of length 0 still paints its cap.
      (done ? `<circle class="cq-ring-fill" cx="17" cy="17" r="${r}" stroke-dasharray="${(c * done / n).toFixed(2)} ${c.toFixed(2)}" transform="rotate(-90 17 17)"/>` : "") + "</svg>" +
      '<div class="cq-heading"><div class="cq-title"></div>' +
      `<div class="cq-count">${all ? "" : `File ${i + 1} of ${n} · `}${done} decided</div></div>` +
      `<div class="cq-nav"${all ? " hidden" : ""}>` +
      `<button type="button" class="cq-btn" data-ctl="prev" data-step="-1"${i === 0 ? " disabled" : ""}>← Prev</button>` +
      `<button type="button" class="cq-btn" data-ctl="skip"${open === undefined ? " disabled" : ""}>Next undecided</button>` +
      `<button type="button" class="cq-btn cq-primary" data-ctl="next" data-step="1"${i === n - 1 ? " disabled" : ""}>Next →</button></div>` +
      `<label class="cq-all"><input type="checkbox" data-ctl="all"${all ? " checked" : ""}${searching ? " disabled" : ""}> Show all</label>`;
    el.querySelector(".cq-title").textContent = run.group;
    el.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
      go(run.key, currentIndex(run) + Number(b.dataset.step));
    }));
    // Not Next: it passes over answered questions to the next open one.
    el.querySelector('[data-ctl="skip"]').addEventListener("click", () => {
      const j = nextUndecided(run, currentIndex(run));
      go(run.key, j === undefined ? currentIndex(run) : j);
    });
    el.querySelector(".cq-all input").addEventListener("change", (e) => {
      save(run, "all", e.target.checked ? "1" : "0");
      refresh();
    });
    return el;
  }

  // The first undecided member after i, wrapping; undefined when none is.
  function nextUndecided(run, i) {
    const n = run.members.length;
    for (let k = 1; k < n; k++) {
      const j = (i + k) % n;
      if (!decided(run.members[j])) return j;
    }
    return undefined;
  }

  function refresh() {
    const root = prose();
    if (!root) return;
    // The bars are rebuilt below, focused button and all. Note which control
    // had focus so the new bar can take it back, or Prev/Next from the
    // keyboard would drop the reader to <body> after one press.
    const active = document.activeElement;
    const hadBar = active && active.closest && active.closest(".cq-bar");
    const keep = hadBar && active.dataset.ctl
      ? { run: hadBar.dataset.run, ctl: active.dataset.ctl } : null;
    root.querySelectorAll(":scope > .cq-bar").forEach((b) => b.remove());
    root.querySelectorAll("." + HIDDEN).forEach((el) => el.classList.remove(HIDDEN));
    for (const run of runs()) {
      const all = expanded(run);
      const i = currentIndex(run);
      run.members.forEach((m, j) => setHidden(m, !all && j !== i));
      run.members[0].insertAdjacentElement("beforebegin", bar(run, i, all));
    }
    if (keep) {
      const b = [...root.querySelectorAll(":scope > .cq-bar")].find((x) => x.dataset.run === keep.run);
      // Next is disabled on the last question and Prev on the first, and a
      // disabled button cannot hold focus, so fall back to the nearest live one.
      const want = b?.querySelector(`[data-ctl="${keep.ctl}"]:not([disabled])`)
        || b?.querySelector(".cq-nav button:not([disabled])");
      want?.focus();
    }
  }

  // Bring a block on screen when it is a hidden member of a collapsed queue:
  // the dock and the change bar jump to blocks, and display:none has no place
  // to scroll to.
  function show(blockId) {
    const run = runs().find((r) => ids(r).includes(blockId));
    if (!run || expanded(run)) return;
    const j = ids(run).indexOf(blockId);
    if (j === currentIndex(run)) return;
    setCurrent(run, j);
    refresh();
  }

  function reveal(sec) {
    window.AnnotateKeyboard?.focusBlock(sec.dataset.blockId);
    sec.scrollIntoView({ block: "nearest" });
  }

  function go(key, j) {
    const run = runs().find((r) => r.key === key);
    if (!run) return;
    setCurrent(run, Math.max(0, Math.min(run.members.length - 1, j)));
    refresh();
    reveal(run.members[currentIndex(run)]);
  }

  // The page's J/K walker asks this first. It moves within the collapsed
  // queue the block belongs to and returns the new current block id, or null
  // when the step would leave the queue and the walker should carry on.
  function stepFrom(blockId, delta) {
    const run = runs().find((r) => ids(r).includes(blockId));
    if (!run || expanded(run)) return null;
    const j = ids(run).indexOf(blockId) + delta;
    if (j < 0 || j >= run.members.length) return null;
    setCurrent(run, j);
    refresh();
    return run.members[j].dataset.blockId;
  }

  let queued = 0;
  function refreshSoon() {
    if (queued) return;
    queued = requestAnimationFrame(() => { queued = 0; refresh(); });
  }

  document.addEventListener("annotate:rendered", refresh);
  document.addEventListener("annotate:choice-changed", refreshSoon);
  document.addEventListener("annotate:search", (e) => {
    searching = !!(e.detail && e.detail.active);
    refresh();
  });
  document.addEventListener("annotate:choice-picked", (e) => {
    const id = e.detail && e.detail.blockId;
    const run = runs().find((r) => ids(r).includes(id));
    if (!run || expanded(run)) return;
    if (nextUndecided(run, ids(run).indexOf(id)) === undefined) return;
    // Long enough to see the pick land before the question changes.
    setTimeout(() => {
      // Look everything up again: a render may have replaced the run in the
      // meantime, and a pick cleared within the delay is no longer a pick.
      const now = runs().find((r) => ids(r).includes(id));
      if (!now || expanded(now)) return;
      const i = ids(now).indexOf(id);
      if (!decided(now.members[i])) return;
      const next = nextUndecided(now, i);
      if (next === undefined) return;
      const old = now.members[i];
      const hadFocus = old.contains(document.activeElement);
      setCurrent(now, next);
      refresh();
      const sec = now.members[next];
      reveal(sec);
      // The focused card just went display:none; hand focus to the new
      // question's tab stop so the keyboard carries on where the eye does.
      if (hadFocus) {
        (sec.querySelector('.choice-option[tabindex="0"]') || sec.querySelector(".choice-option"))?.focus();
      }
    }, 180);
  });

  window.AnnotateChoiceQueue = { refresh, stepFrom, show };
  refresh();
})();
