// ---- the conversation --------------------------------------------------
// Keyed: each entry keeps its element until what it shows changes, so a new entry leaves the others
// (and a text selection in them) alone.
const nodes = new Map();    // entry id -> {el, sig}
let rendered = false;
const sigOf = e => `${e.who}|${e.text.length}|${e.speech}|${e.words?.length || 0}|${e.speech_error || ""}|${e.n || 0}|${e.withdrawn ? 1 : 0}`;

const unfolded = new Set();  // the answers whose text the reader opened
const staged = (e) => !!CFG.stageUrl && (e.cues || []).some((c) => c.kind === "front");
function buildEntry(e) {
  let el;
  if (e.who === "you" || e.who === "claude") {
    el = document.createElement("div"); el.className = "turn " + e.who + (e.withdrawn ? " withdrawn" : "");
    const who = document.createElement("div"); who.className = "who"; who.textContent = e.who === "you" ? "You" : "Claude";
    if (e.who === "claude") { const s = document.createElement("small"); s.textContent = "answer " + e.n; who.append(s); }
    if (e.typed) { const s = document.createElement("small"); s.textContent = "typed"; who.append(s); }
    const text = document.createElement("div"); text.className = "text";
    // An answer's timed words are spans: the one being said is lit, and a tap plays from there.
    if (e.who === "claude") text.replaceChildren(...wordSpans(e)); else text.textContent = e.text;
    el.dataset.id = e.id;
    el.append(who, text);
    if (e.who === "claude" && readerOn()) {
      // The stage reads every answer in large type: in the panel its text folds to one line until opened.
      el.classList.toggle("folded", !unfolded.has(e.id));
      const f = document.createElement("button"); f.type = "button"; f.className = "fold";
      const paintFold = () => { f.textContent = el.classList.contains("folded") ? "Show text" : "Hide text"; };
      f.onclick = () => { if (unfolded.has(e.id)) unfolded.delete(e.id); else unfolded.add(e.id); el.classList.toggle("folded", !unfolded.has(e.id)); paintFold(); };
      paintFold(); who.append(f);
    }
    if (e.who === "claude") {
      if (e.speech === "ready") {
        const b = document.createElement("button"); b.className = "play"; b.type = "button";
        b.onclick = () => { if (current && current.id === e.id && !audio.paused) { audio.pause(); return; } readerPlays(e); takeVoice(); load(view.entries.find(x => x.id === e.id) || e, true); };
        who.append(b);
      } else if (e.speech === "failed") {   // the voice being made shows in the foot, with its progress
        const s = document.createElement("div"); s.className = "speech bad";
        s.textContent = "Not read aloud: " + (e.speech_error || "speech failed"); el.append(s);
      }
      paintTurn(el, e.id);
    }
  } else if (e.who === "status") {
    el = document.createElement("div"); el.className = "line status"; el.textContent = e.text;
  } else if (e.who === "board") {
    // A button: it brings its board to the front of the stage, and the sheet steps aside to show it.
    el = document.createElement("button"); el.type = "button"; el.className = "chip board"; el.dataset.view = e.view || "";
    el.innerHTML = kindIcon(e.kind);
    const t = document.createElement("span"); t.textContent = e.text; el.append(t);
    el.setAttribute("aria-label", e.kind === "points" ? e.text : "On the stage: " + e.text);
    if (!CFG.stageUrl || !e.view) { el.disabled = true; el.title = "The stage is not available"; }
    else el.onclick = () => chipTap(e.view);
  } else if (e.who === "note") {
    el = document.createElement("div"); el.className = "chip note"; el.textContent = "Noted: " + e.text;
  } else {
    el = document.createElement("div"); el.className = "line system"; el.textContent = e.text;
  }
  return el;
}

const KIND_ICONS = {
  code: '<path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4"/>',
  diagram: '<rect x="1.5" y="1.5" width="6" height="4.5" rx="1.2"/><rect x="8.5" y="10" width="6" height="4.5" rx="1.2"/><path d="M4.5 6v3a1.5 1.5 0 0 0 1.5 1.5h2.5"/>',
  table: '<rect x="1.5" y="2.5" width="13" height="11" rx="1.6"/><path d="M1.5 6.5h13M6 6.5v7"/>',
  change: '<path d="M4.5 2v6M1.5 5h6M8.5 12.5h6"/>',
  points: '<path d="M6 4h8M6 8h8M6 12h8"/><circle cx="2.6" cy="4" r=".9"/><circle cx="2.6" cy="8" r=".9"/><circle cx="2.6" cy="12" r=".9"/>',
  page: '<path d="M3.5 1.5h6l3 3v10h-9z"/><path d="M9.5 1.5v3h3M5.5 8.5h5M5.5 11h5"/>',
  scene: '<rect x="1.5" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="9" y="2.5" width="5.5" height="5" rx="1.2"/><rect x="1.5" y="10" width="13" height="3.5" rx="1.2"/>',
};
const kindIcon = kind => `<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${KIND_ICONS[kind] || KIND_ICONS.page}</svg>`;

function place(prev, el) { if (prev.nextElementSibling !== el) prev.after(el); return el; }
// The boards of one answer share one row of chips, labelled once, keyed by the run's first entry.
const chipRows = new Map();  // first board entry id -> row element
function chipRow(id) {
  let row = chipRows.get(id);
  if (!row) {
    row = document.createElement("div"); row.className = "chips"; row.setAttribute("role", "group");
    row.setAttribute("aria-label", "On the stage");
    const l = document.createElement("span"); l.className = "clbl"; l.textContent = "On the stage"; l.setAttribute("aria-hidden", "true");
    row.append(l); chipRows.set(id, row);
  }
  return row;
}

let pinnedEnd = false;      // the conversation was at its end when it last painted, so a resize of its box keeps it there
if (typeof ResizeObserver === "function") new ResizeObserver(() => { const box = $("convo"); if (pinnedEnd) box.scrollTop = box.scrollHeight; }).observe($("convo"));
function render() {
  const box = $("convo"), atEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  $("empty").hidden = !!view.entries.length;
  let prev = $("empty"), row = null, inRow = null;
  const live = new Set(), rows = new Set();
  for (const e of view.entries) {
    live.add(e.id);
    const sig = sigOf(e);
    let rec = nodes.get(e.id);
    if (!rec) { rec = {el: buildEntry(e), sig}; nodes.set(e.id, rec); }
    else if (rec.sig !== sig) { const el = buildEntry(e); rec.el.replaceWith(el); rec.el = el; rec.sig = sig; }
    if (e.who === "board") {
      if (!row) { row = chipRow(e.id); rows.add(e.id); prev = place(prev, row); inRow = row.firstElementChild; }
      inRow = place(inRow, rec.el);
    } else { row = null; prev = place(prev, rec.el); }
  }
  for (const [id, rec] of nodes) if (!live.has(id)) { rec.el.remove(); nodes.delete(id); }
  for (const [id, r] of chipRows) if (!rows.has(id)) { r.remove(); chipRows.delete(id); }
  // New lines land at the end: a reader already there sees them, unless the voice is being followed elsewhere.
  const stick = atEnd && !(current && !audio.paused && convoFollow);
  if (stick) box.scrollTop = box.scrollHeight;
  paintFront();
  paintCalls();
  paintAll();
  // paintAll changes the foot (the working line, the status), so the conversation's box is shorter or taller
  // than it was: the newest message goes to the end again, never cut off at the bottom.
  pinnedEnd = stick;
  if (stick) box.scrollTop = box.scrollHeight;
  rendered = true;
  if (audio.paused) highlight(); else paintReader();
}

// Only the turn that is in the player is drawn as a card, with Pause on its button.
function paintTurn(el, id) {
  const on = !!current && current.id === id;
  el.classList.toggle("now", on);
  const b = el.querySelector("button.play"); if (b) b.textContent = on && !audio.paused ? "Pause" : "▶ Play";
}
let nowId = null;
function paintNow() {
  for (const id of new Set([nowId, current ? current.id : null])) {
    const rec = id === null ? null : nodes.get(id);
    if (rec && rec.el.classList.contains("claude")) paintTurn(rec.el, id);
  }
  nowId = current ? current.id : null;
}

// ---- the answer being read: the one in the player, else the last one -------------
function lastAnswer() {
  for (let i = view.entries.length - 1; i >= 0; i--) if (view.entries[i].who === "claude") return view.entries[i];
  return null;
}
function shownAnswer() { return current ? (view.entries.find(e => e.id === current.id) || current) : lastAnswer(); }
function wordSpans(e) {
  if (!e.words || !e.words.length) return [document.createTextNode(e.text)];
  const out = [];
  let pos = 0;
  e.words.forEach((w, i) => {
    if (w[0] > pos) out.push(document.createTextNode(e.text.slice(pos, w[0])));
    const span = document.createElement("span"); span.className = "w"; span.dataset.i = i;
    span.textContent = e.text.slice(w[0], w[1]); span.onclick = () => playFrom(e, w[2]);
    out.push(span); pos = w[1];
  });
  out.push(document.createTextNode(e.text.slice(pos)));
  return out;
}
// The turn in the player and its word spans; the turn is built again when its words arrive.
let readEl = null, readSpans = [];
function readingTurn() {
  const el = current ? nodes.get(current.id)?.el || null : null;
  if (el !== readEl) { readEl = el; readSpans = el ? [...el.querySelectorAll(".text .w")] : []; lastWord = null; lastK = -2; }
  return el;
}
function paintNowLine() {
  const e = current && (view.entries.find(x => x.id === current.id) || current);
  let text = "";
  if (e && e.words && e.words.length && !audio.paused) {
    const starts = sentenceTimes(e), t = audio.currentTime || 0;
    const i = Math.max(0, starts.findLastIndex(x => x <= t + 0.05));
    const from = e.words.findIndex(w => w[2] >= starts[i]);
    const to = i + 1 < starts.length ? e.words.findIndex(w => w[2] >= starts[i + 1]) : e.words.length;
    text = e.text.slice(e.words[from][0], e.words[Math.max(from, to - 1)][1]);
  }
  if ($("nowline").textContent !== text) { $("nowline").textContent = text; $("nowline").title = text; }
}
// The conversation follows the voice: the word being said stays in view, until the reader scrolls
// away from it. Then "Back to the voice" brings it back, and following goes on.
let convoFollow = true, ownScroll = 0;
function scrollConvo(top) {
  const box = $("convo");
  if (Math.abs(box.scrollTop - top) < 2) return;
  ownScroll = performance.now();
  box.scrollTo({top, behavior: reduced.matches ? "auto" : "smooth"});
}
function inView(el) {
  const box = $("convo").getBoundingClientRect(), r = el.getBoundingClientRect();
  return r.bottom > box.top + 8 && r.top < box.bottom - 8;
}
function followVoice(force) {
  if (rail || !(convoFollow || force)) return;
  const box = $("convo"), word = lastWord, turn = readEl;
  if (word) {
    const top = word.offsetTop - box.offsetTop, h = box.clientHeight;
    if (force || top < box.scrollTop + 24 || top > box.scrollTop + h - 48) scrollConvo(Math.max(0, top - h * 0.6));
  } else if (turn && force) scrollConvo(Math.max(0, turn.offsetTop - box.offsetTop - 12));
}
$("convo").addEventListener("scroll", () => {
  const box = $("convo");
  pinnedEnd = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  if (performance.now() - ownScroll < 900) return;   // a scroll this page made
  const reading = !!current && !audio.paused && !!lastWord;
  convoFollow = !reading || inView(lastWord);
  paintJump();
}, {passive: true});
function paintJump() { $("jump").hidden = convoFollow || rail || !current || audio.paused; }
$("jump").onclick = () => { convoFollow = true; followVoice(true); paintJump(); };
// The word being said is lit in the answer being read, the words before it are full ink, and the
// conversation keeps it in view. A paused answer keeps its place; one played to its end reads in full.
let lastWord = null, lastK = -2, lastTurn = null;
function highlight() {
  const e = current;
  let k = -1;
  if (e && e.words && e.words.length && !audio.ended) {
    if (audio.currentTime > 0) k = wordAt(e, audio.currentTime);
    const unheard = !sent && e.id > (view.heard_upto ?? -1);
    if (audio.currentTime > 0 || (cueSync && ((sent && sent.id === e.id) || unheard))) {
      const lead = wordAt(e, audio.currentTime + LEAD_S * (audio.playbackRate || 1));
      syncStage(e, Math.min(lead >= 0 ? e.words[lead][0] : -1, heldAt(e) - 1));
    }
    if (audio.currentTime > 0) caption(e, audio.currentTime);
    checkStop(e);
  }
  paintReader();
  const turn = readingTurn();
  if (lastTurn && lastTurn !== turn) {
    lastTurn.classList.remove("reading");
    for (const w of lastTurn.querySelectorAll(".w.said, .w.now-word")) w.classList.remove("said", "now-word");
  }
  lastTurn = turn;
  const reading = !!turn && k >= 0;
  if (turn) turn.classList.toggle("reading", reading);
  if (!reading) k = -1;
  if (k === lastK) return;
  lastK = k;
  for (let i = 0; i < readSpans.length; i++) readSpans[i].classList.toggle("said", i < k);
  if (lastWord) lastWord.classList.remove("now-word");
  lastWord = k >= 0 ? readSpans[k] || null : null;
  if (lastWord) { lastWord.classList.add("now-word"); followVoice(false); }
  if (!audio.paused) paintNowLine();
}

$("playpause").onclick = $("railpp").onclick = togglePlay;
$("back").onclick = $("railback").onclick = () => skip(-10);
$("seek").oninput = () => { audio.currentTime = Number($("seek").value); paintPill(); };
for (const ev of ["play", "pause", "ended", "durationchange", "loadedmetadata"]) audio.addEventListener(ev, paintAll);
audio.addEventListener("timeupdate", paintPill);
// The frame loop does not run in a tab out of sight: the audio's own timeupdate still does, so a hidden tab
// stops at a check or guess too.
audio.addEventListener("timeupdate", () => { if (current) checkStop(view.entries.find(x => x.id === current.id) || current); });
for (const ev of ["play", "pause", "ended"]) audio.addEventListener(ev, paintNow);
audio.addEventListener("play", startHighlight);
for (const ev of ["pause", "ended"]) audio.addEventListener(ev, stopHighlight);
audio.addEventListener("seeked", () => { if (audio.paused) highlight(); });

// ---- the hooks this file owns (C) -----------------------------------------------
// The player's controls, painted from paintPill(): the foot's player and the rail's ring and buttons.
function paintTransport() {
  const rec = !!recorder, shown = shownAnswer();
  const playable = !rec && !!shown && shown.speech === "ready";
  $("player").hidden = !playable; $("ring").hidden = !playable;
  $("back").disabled = !current; $("railback").hidden = !playable || !current;
  const label = !audio.paused ? "Pause" : (current && (audio.ended || audio.currentTime >= (audio.duration || 1)) ? "Play again" : "Play");
  for (const id of ["playpause", "railpp"]) {
    $(id).setAttribute("aria-label", label); $(id).dataset.tip = label + " · Space"; $(id).classList.toggle("playing", !audio.paused);
  }
  const d = audio.duration || 0, p = d ? 100 * audio.currentTime / d : 0;
  $("seek").max = d; $("seek").value = audio.currentTime || 0;
  $("seek").style.setProperty("--p", p + "%"); $("ring").style.setProperty("--p", p + "%");
  $("time").textContent = current ? fmt(audio.currentTime) + " / " + fmt(d) : "";
}
// The Now card (#nowcard) and everything in it that is C's, from paintAll().
function paintNowCard() {}
// The list of earlier answers (#earlier, rows .tlrow in #tllist), its search and Expand all, from paintAll(). After it has
// placed its rows it calls returnMarkEarlier(#tllist) so call-return.js can put the since-you-left divider in.
function paintEarlier() {}
// A new view arrived: `before` is the one it replaces.
function shellOnView(before) {}
