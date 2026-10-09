// The call page: the stage beside a panel that holds the conversation, the player, the text field and
// the mic; the panel collapses to a rail; a gear holds the settings. talk.py serves it with window.CFG filled in for one call.
const CFG = window.CFG;
const $ = id => document.getElementById(id);
const SPEEDS = [0.75, 0.85, 1, 1.25, 1.5];
const store = {get(k, d){ try { const v = localStorage.getItem("talk." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
               set(k, v){ try { localStorage.setItem("talk." + k, JSON.stringify(v)); } catch {} }};
const api = (path, opts = {}) => fetch(path, {...opts, headers: {"X-Talk-Token": CFG.token, ...(opts.headers || {})}});
const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

$("topic").textContent = CFG.topic; $("topic").title = CFG.topic; document.title = "Talk · " + CFG.topic;
// Which engine reads the answers aloud, in the settings: Azure is fast and billed, VoiceStudio is local and slow.
if (CFG.engine) {
  const ava = /^[a-z]{2}-[A-Z]{2}-([A-Z][a-z]+)/.exec(CFG.voice || "");
  $("engine").textContent = CFG.engine === "Azure" ? "Azure · " + (ava ? ava[1] : CFG.voice) + ": fast, billed per character"
    : "VoiceStudio on this Mac, profile " + CFG.voice + ": free, slower";
  $("engine").hidden = false;
}
const audio = $("audio");

// ---- the stage ---------------------------------------------------------
// A veil covers the stage until it has loaded; one that does not load in time says so and offers buttons.
let stageTimer = null;
function stageReady() { clearTimeout(stageTimer); $("veil").hidden = true; }
function stageFailed() { $("veilwait").hidden = true; $("veilfail").hidden = false; }
function loadStage() {
  stageUp = false;
  $("veil").hidden = false; $("veilwait").hidden = false; $("veilfail").hidden = true;
  clearTimeout(stageTimer); stageTimer = setTimeout(stageFailed, window.__stageTimeoutMs || 10000);
  $("stage").src = CFG.stageUrl;
}
if (CFG.stageUrl) {
  $("openstage").href = CFG.stageUrl;
  // Only the stage saying it is ready counts: a page that failed to load fires "load" too (Chrome's own
  // error page), and that must show the Reload box, not an empty frame.
  $("stage").addEventListener("load", () => {
    if (!$("stage").getAttribute("src") || stageUp) return;
    clearTimeout(stageTimer); stageTimer = setTimeout(() => { if (!stageUp) stageFailed(); }, window.__stageReadyMs || 4000);
  });
  $("reloadstage").onclick = loadStage;
  loadStage();
} else { $("stagewrap").remove(); $("nostage").hidden = false; }

// ---- talk and stage talk to each other -----------------------------------
// The protocol, also described at the top of stage.js. Talk to stage, posted to the stage's origin:
//   {type:'stage:front', view, manual, answer}  bring a board to the front; manual: a chip was pressed
//   {type:'stage:frame', view, n, animate, answer}  show frame n of the scene answer number `answer` said the
//                                       board with (each answer keeps its own), animated when it is the next one
//   {type:'stage:state', front, frames, keys, answer}  after a jump: the board in front, every scene's frame
//                                       (of that answer's scenes), the key point lit
//   {type:'stage:answer', n}            answer n started playing
//   {type:'stage:rest', views, answer}  that answer ended a moment ago: these boards, still on its scenes, show whole
//   {type:'stage:key', view, index}     key point number index (from 1) was just said: light it up
//   {type:'stage:theme', theme}         'light' or 'dark': the theme chosen here
//   {type:'stage:follow', on}           the gear's switch turned following on or off
// Stage to talk: {type:'stage:ready'}, {type:'stage:views', list:[{name, title, kind, answer}]} on every
// change, {type:'stage:changed', name, title, isNew}, and {type:'stage:follow', on} when following
// changes inside the stage (a tab tap, a chip or a step by hand turns it off, a new answer on; a play the
// reader starts turns it on from here), {type:'stage:key', key} for Space, ← or →
// pressed on the stage with nothing there taking them, and {type:'stage:missing', view} when a chip
// asked for a view it does not hold: such chips are struck through. Only messages from the embedded stage's own
// window and origin are read. Until the stage says it is ready, what talk sends waits in a short queue.
var stageUp = false;
const stageOrigin = CFG.stageUrl ? new URL(CFG.stageUrl, location.href).origin : null;
const stageOutbox = [];
function toStage(msg) {
  if (!stageOrigin || !$("stage")) return;
  if (!stageUp) { stageOutbox.push(msg); if (stageOutbox.length > 20) stageOutbox.shift(); return; }
  try { $("stage").contentWindow.postMessage(msg, stageOrigin); } catch {}
}
window.addEventListener("message", ev => {
  if (!stageOrigin || !$("stage") || ev.source !== $("stage").contentWindow || ev.origin !== stageOrigin) return;
  const m = ev.data;
  if (!m || typeof m !== "object") return;
  if (m.type === "stage:ready") {
    // Every ready, a first load or a stage page loaded again, starts from the page's own state: the
    // theme and following go first, and the queue's older copies of them are dropped.
    stageUp = true; stageReady();
    toStage({type: "stage:theme", theme: document.documentElement.dataset.theme});
    toStage({type: "stage:zoom", zoom: screenMode === "tv" ? TV_ZOOM : 1});
    toStage({type: "stage:follow", on: follow});
    for (const msg of stageOutbox.splice(0)) if (msg.type !== "stage:theme" && msg.type !== "stage:follow") toStage(msg);
    resync();
  }
  else if (m.type === "stage:follow") { follow = !!m.on; paintSettings(); if (follow) resync(); }
  else if (m.type === "stage:views") {
    stageViews = new Set((m.list || []).map(v => String(v.name)));
    boardAnswer = new Map((m.list || []).map(v => [String(v.name), v.answer]));
    paintMissing();
  }
  else if (m.type === "stage:shown") { frontBoard = String(m.view || ""); paintFront(); }
  else if (m.type === "stage:missing") paintMissing(String(m.view));
  else if (m.type === "stage:key" && MEDIA_KEYS.has(m.key)) mediaKey(m.key);
});

let stageViews = null;
let boardAnswer = new Map();   // board -> the number of the answer that showed it
let frontBoard = "";           // the board in front of the stage
const chipSeen = new Map();
const MISSING_AFTER_MS = 8000;
function paintMissing(gone) {
  const now = Date.now();
  for (const el of document.querySelectorAll("button.chip.board[data-view]")) {
    const v = el.dataset.view;
    if (!v) continue;
    if (!chipSeen.has(v)) chipSeen.set(v, now);
    const missing = v === gone || (!!stageViews && !stageViews.has(v) && now - chipSeen.get(v) > MISSING_AFTER_MS);
    el.classList.toggle("missing", missing);
    if (missing) el.title = "Not on the stage: this board never reached it";
    else if (el.title.startsWith("Not on the stage")) el.removeAttribute("title");
  }
}
setInterval(() => { if (stageViews) paintMissing(); }, MISSING_AFTER_MS / 2);
// The chip of the board in front of the stage is drawn as chosen, wherever it is in the conversation.
function paintFront() {
  for (const el of document.querySelectorAll("button.chip.board[data-view]")) el.classList.toggle("front", !!frontBoard && el.dataset.view === frontBoard);
}

// ---- the theme: light, dark, or the system's ------------------------------
// <html> always carries data-theme; the head script set it before the first paint.
const darkMq = matchMedia("(prefers-color-scheme: dark)");
let theme = ["light", "dark", "system"].includes(store.get("theme", "light")) ? store.get("theme", "light") : "light";
function applyTheme() {
  const t = theme === "dark" || (theme === "system" && darkMq.matches) ? "dark" : "light";
  document.documentElement.dataset.theme = t;
  toStage({type: "stage:theme", theme: t});
  for (const b of $("theme").children) b.setAttribute("aria-pressed", String(b.dataset.choice === theme));
}
for (const b of $("theme").children) b.onclick = () => { theme = b.dataset.choice; store.set("theme", theme); applyTheme(); };
darkMq.addEventListener("change", () => { if (theme === "system") applyTheme(); });

// ---- following the voice: the stage keeps it, the gear shows it -------------
let follow = true;
$("follow").onclick = () => { follow = !follow; toStage({type: "stage:follow", on: follow}); paintSettings(); if (follow) resync(); };

// ---- full screen: the whole page, stage and pill, for a TV or a call that needs the room ----
function paintFullscreen() {
  const on = !!document.fullscreenElement;
  $("fullscreen").setAttribute("aria-pressed", String(on));
  $("fullscreen").setAttribute("aria-label", on ? "Leave full screen" : "Full screen");
  $("fullscreen").dataset.tip = on ? "Leave full screen" : "Full screen";
}
// A browser that cannot take the page full screen (an iPhone, a frame without the permission) shows no button.
$("fullscreen").hidden = !document.fullscreenEnabled;
$("fullscreen").onclick = () => {
  const go = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  go.catch(err => showError("Full screen failed: " + err.message));
};
// Esc and the browser's own controls leave full screen too: the button follows whatever happened.
document.addEventListener("fullscreenchange", paintFullscreen);

// ---- popovers: one open at a time ---------------------------------------------
const POPS = {callsbtn: "pCalls", gear: "pGear", railgear: "pGear"};
let openPop = null;
function showPop(pop) {
  openPop = pop && openPop !== pop ? pop : null;
  for (const id of new Set(Object.values(POPS))) $(id).hidden = id !== openPop;
  for (const [btn, id] of Object.entries(POPS)) $(btn).setAttribute("aria-expanded", String(id === openPop));
}
for (const [btn, id] of Object.entries(POPS)) $(btn).onclick = ev => { ev.stopPropagation(); showPop(id); };
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && openPop) showPop(null); });
// A click anywhere else closes the open layer: the buttons that open layers stop their own click.
document.addEventListener("click", ev => {
  if (openPop && !ev.target.closest(".pop, .toast")) showPop(null);
});

// ---- the panel: on the left or the right, as wide as dragged, or collapsed to a rail ----
const PANEL_W = [300, 640];
let side = store.get("side", "right") === "left" ? "left" : "right";
let rail = store.get("panel", "open") === "rail";
let panelW = Math.min(PANEL_W[1], Math.max(PANEL_W[0], Number(store.get("panelW", 380)) || 380));
function paintPanel() {
  $("app").dataset.side = side;
  $("app").toggleAttribute("data-rail", rail);
  document.documentElement.style.setProperty("--pw", panelW + "px");
  for (const b of $("side").children) b.setAttribute("aria-pressed", String(b.dataset.choice === side));
}
function setRail(on) {
  rail = on; store.set("panel", on ? "rail" : "open"); showPop(null); paintPanel();
  if (!on) { convoFollow = true; followVoice(true); }
}
$("collapse").onclick = () => setRail(true);
$("expand").onclick = () => setRail(false);
for (const b of $("side").children) b.onclick = () => { side = b.dataset.choice; store.set("side", side); paintPanel(); };
$("grip").onpointerdown = ev => {
  const grip = $("grip"); grip.setPointerCapture(ev.pointerId); grip.classList.add("on");
  grip.onpointermove = m => {
    const w = side === "left" ? m.clientX : innerWidth - m.clientX;
    panelW = Math.round(Math.min(PANEL_W[1], Math.max(PANEL_W[0], w)));
    paintPanel();
  };
  grip.onpointerup = grip.onpointercancel = () => { grip.onpointermove = null; grip.classList.remove("on"); store.set("panelW", panelW); };
};
paintPanel();
// A click on the stage lands in its own page, which takes the focus away from this one.
window.addEventListener("blur", () => {
  setTimeout(() => { if (openPop && document.activeElement === $("stage")) showPop(null); }, 0);
});

// ---- the toast: an error for a while, or a lost connection until it is back ----
let errText = "", errTimer = null, connText = "", connDown = false;
let unsent = null;          // a recording the server did not take: kept, so the user never says it twice
function paintToast() {
  const text = connText || errText || (unsent ? "Your recording was not sent." : "");
  $("toast").hidden = !text; $("toasttext").textContent = text;
  $("retry").hidden = !connDown && !unsent; $("retry").textContent = connDown ? "Retry" : "Send again";
}
function showError(text) {
  errText = text || ""; clearTimeout(errTimer);
  if (errText) errTimer = setTimeout(() => { errText = ""; paintToast(); }, 12000);
  paintToast();
}

// ---- state -------------------------------------------------------------
let view = {v: -1, entries: [], working: false, stalled: false, activity: [], ended: null, calls: [], floor_call: null, floor_n: 0};
let seen = null;            // ids of answers that existed when the page loaded: never auto-played
let current = null;         // the entry in the player
// A language the launch named wins; with none named, the one the user last picked on this origin.
let language = CFG.language && CFG.language !== "auto" ? CFG.language : store.get("language", "auto");
let speed = store.get("speed", 1);
let autoplay = store.get("autoplay", true);
let recorder = null;
let starting = false;       // the microphone is being asked for: a second press must not open a second one
let busy = false;           // the recording is being turned into text
let closed = false;         // the ended call was closed from here
let talkMode = store.get("talkMode", "manual") === "live" ? "live" : "manual";  // live: the microphone stays open
let barge = store.get("barge", "talk") === "keyword" ? "keyword" : "talk";    // how live speech interrupts an answer
let endPause = [800, 1200, 2000].includes(store.get("endPause", 1200)) ? store.get("endPause", 1200) : 1200;
let live = null;            // the open microphone of live mode, while it listens
let held = null;            // the answer the user's speech is over: ducked, paused, or waiting after a cue word
let deferred = null;        // a new answer that came while the user was talking: it plays once they are done
let liveNote = "";          // why live mode is not listening, when it stopped by itself
let liveFlash = null;       // a short-lived line: {text, until}
let screenMode = store.get("screen", "desk") === "tv" ? "tv" : "desk";  // tv: everything read from across the room
const TV_ZOOM = 1.35;
let undoable = null;        // {entry, until}: the live turn the Undo button can still take back
let fillerFor = null, turnSentAt = 0;  // "One moment." is said once per turn, when Claude takes a while

// ---- the conversation --------------------------------------------------
// Keyed: each entry keeps its element until what it shows changes, so a new entry leaves the others
// (and a text selection in them) alone.
const nodes = new Map();    // entry id -> {el, sig}
let rendered = false;
const sigOf = e => `${e.who}|${e.text.length}|${e.speech}|${e.words?.length || 0}|${e.speech_error || ""}|${e.n || 0}|${e.withdrawn ? 1 : 0}`;

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
    if (e.who === "claude") {
      if (e.speech === "ready") {
        const b = document.createElement("button"); b.className = "play"; b.type = "button";
        b.onclick = () => { if (current && current.id === e.id && !audio.paused) { audio.pause(); return; } toVoice(); load(view.entries.find(x => x.id === e.id) || e, true); };
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
    else el.onclick = () => toStage({type: "stage:front", view: e.view, manual: true});
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
  if (atEnd && !(current && !audio.paused && convoFollow)) box.scrollTop = box.scrollHeight;
  paintFront();
  paintCalls();
  paintAll();
  rendered = true;
  if (audio.paused) highlight();
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
// The foot's line: what Claude is doing, the voice being made, Undo; the rail's line: the sentence being said.
function paintInfo() {
  const s = statusText(), e = shownAnswer();
  $("status").hidden = !s;
  if (s) { $("status").textContent = s.text; $("status").className = "status" + (s.shimmer ? " shimmer" : "") + (s.warn ? " warn" : ""); }
  paintPrep(recorder ? null : e);
  $("wave").hidden = !recorder;
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
  if (performance.now() - ownScroll < 900) return;   // a scroll this page made
  const reading = !!current && !audio.paused && !!lastWord;
  convoFollow = !reading || inView(lastWord);
  paintJump();
}, {passive: true});
function paintJump() { $("jump").hidden = convoFollow || rail || !current || audio.paused; }
$("jump").onclick = () => { convoFollow = true; followVoice(true); paintJump(); };
// The line under the stage while there is no answer to read: the first that applies.
function statusText() {
  if (recorder) return null;
  if (live && live.speech) return {text: "Hearing you…"};
  if (live && live.suspended) return {text: "Click anywhere to start listening.", warn: true};
  if (live && live.parked) return {text: live.parked === "floor" ? "Listening in another call. Press the mic to listen here."
    : "Listening on another screen. Press the mic to listen here."};
  if (held && held.armed && !busy) return {text: "Listening. Go ahead."};
  if (liveFlash && Date.now() < liveFlash.until && !busy) return {text: liveFlash.text};
  if (busy) return {text: "Turning your words into text…", shimmer: true};
  if (view.ended) return {text: closed ? "Closed. You can close this tab." : "The call has ended: " + view.ended + ". Answers can still be replayed."};
  if (view.stalled) return {text: "Claude has not picked this up yet. Check the terminal: the session may be waiting for a permission.", warn: true};
  if (view.working) {
    const run = view.activity.filter(a => a.state === "running").pop();
    return {text: run ? run.label + " · " + Math.round(run.seconds) + "s" : "Claude is working…", shimmer: true};
  }
  // Whether live mode listens shows on the corner chip, the mic and the frame's edge; the card only says
  // why it stopped when it stopped by itself (asleep, the microphone lost).
  if (talkMode === "live" && !live && liveNote) return {text: liveNote};
  return null;
}
function appState() {
  if (recorder || (live && live.speech)) return "listening";
  if (busy || (view.working && !view.ended)) return "working";
  if (current && !audio.paused) return "speaking";
  return "idle";
}
function paintPill() {
  const rec = !!recorder, ended = !!view.ended, shown = shownAnswer();
  const liveMode = talkMode === "live";
  const liveLabel = !live ? "Listen" : live.suspended ? "Start listening" : live.parked ? "Listen here" : "Stop listening";
  const talkLabel = rec ? "Send" : liveMode ? liveLabel : "Talk";
  // The rail's mic is the panel's: the same label, the same look.
  for (const id of ["talk", "railtalk"]) {
    const b = $(id);
    b.hidden = ended; b.disabled = busy && !liveMode; b.classList.toggle("busy", busy && !liveMode);
    b.setAttribute("aria-label", talkLabel); b.dataset.tip = talkLabel;
    b.classList.toggle("live", liveMode); b.classList.toggle("muted", liveMode && !listening());
  }
  $("cancel").hidden = !rec; $("send").hidden = !rec;
  $("text").hidden = rec || ended; $("sendtext").hidden = rec || ended; $("pill").hidden = ended && !rec;
  const playable = !rec && !!shown && shown.speech === "ready";
  $("player").hidden = !playable; $("ring").hidden = !playable;
  $("back").disabled = !current; $("railback").hidden = !playable || !current;
  const label = !audio.paused ? "Pause" : (current && (audio.ended || audio.currentTime >= (audio.duration || 1)) ? "Play again" : "Play");
  for (const id of ["playpause", "railpp"]) {
    $(id).setAttribute("aria-label", label); $(id).dataset.tip = label + " · Space"; $(id).classList.toggle("playing", !audio.paused);
  }
  const calls = view.calls || [];
  $("callsbtn").hidden = !calls.length;
  $("callsdot").hidden = $("raildot").hidden = !calls.some(c => c.unheard);
  const d = audio.duration || 0, p = d ? 100 * audio.currentTime / d : 0;
  $("seek").max = d; $("seek").value = audio.currentTime || 0;
  $("seek").style.setProperty("--p", p + "%"); $("ring").style.setProperty("--p", p + "%");
  $("time").textContent = current ? fmt(audio.currentTime) + " / " + fmt(d) : "";
  $("live").classList.toggle("off", ended); $("raillive").classList.toggle("off", ended);
  paintNowLine(); paintJump();
}
function paintSettings() {
  for (const b of $("speeds").children) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
  for (const b of $("lang").children) b.setAttribute("aria-pressed", String(b.dataset.lang === language));
  $("autoplay").setAttribute("aria-pressed", String(autoplay));
  $("follow").setAttribute("aria-pressed", String(follow)); $("follow").disabled = !CFG.stageUrl;
  for (const b of $("tmode").children) b.setAttribute("aria-pressed", String(b.dataset.choice === talkMode));
  for (const b of $("barge").children) b.setAttribute("aria-pressed", String(b.dataset.choice === barge));
  for (const b of $("endpause").children) b.setAttribute("aria-pressed", String(+b.dataset.choice === endPause));
  $("liveopts").hidden = talkMode !== "live";
  for (const b of $("screen").children) b.setAttribute("aria-pressed", String(b.dataset.choice === screenMode));
  $("endlbl").textContent = view.ended ? "Close" : "End call"; $("end").disabled = closed;
}
function paintAll() {
  if (view.ended && live) { stopLive(); return; }  // stopLive paints again
  paintInfo(); paintPill(); paintSettings();
  $("app").dataset.state = appState(); $("app").toggleAttribute("data-ended", !!view.ended);
  $("app").toggleAttribute("data-live", listening());
  $("app").toggleAttribute("data-tv", screenMode === "tv");
  // The mode, always on screen: from across the room the mic button alone does not say it.
  $("modechip").textContent = talkMode === "manual" ? "Press to talk" : listening() ? "Live · listening" : "Live · off";
  $("modechip").classList.toggle("on", listening());
  const canUndo = !!undoable && Date.now() < undoable.until && !view.ended;
  $("undo").hidden = !canUndo;
}

// ---- the connection ------------------------------------------------------
let fails = 0, failingSince = 0, wake = null, backUntil = 0, backTimer = null;
const BACK_MS = 4000;
async function pollOnce() {
  try {
    const epoch = floorEpoch;
    const r = await api("/api/state?v=" + view.v);
    if (r.status === 403 || r.status === 410) {
      if (!view.ended) { view = {...view, ended: "the talk server no longer holds this call", working: false}; render(); }
      return true;
    }
    if (!r.ok) return false;
    const body = await r.json();
    if (!body.same) {
      view = body;
      if (view.now) clockSkew = view.now - Date.now() / 1000;
      // A floor taken here after this poll left is newer than what it brought back.
      if (epoch === floorEpoch && view.floor_n > floorN) {
        floorN = view.floor_n;
        if (view.floor_call && view.floor_call !== CFG.call) yieldFloor(view.floor_call);
      }
      if (seen === null) seen = new Set(view.entries.filter(e => e.who === "claude").map(e => e.id));
      let n = 0; for (const e of view.entries) if (e.who === "claude") e.n = ++n;
      if (current) current = view.entries.find(e => e.id === current.id) || current;
      maybeAutoplay();
      showFailedAnswer();
      render();
    }
    return true;
  } catch (err) { return false; }
}
function paintConn() {
  // An ended call says so under the stage; its server going away is expected then.
  connDown = fails >= 2 && !view.ended;
  connText = connDown ? (Date.now() - failingSince > 30000 ? "The call server is not answering. Still trying…" : "Reconnecting to the call…")
    : Date.now() < backUntil && !view.ended ? "Reconnected." : "";
  paintToast();
}
async function poll() {
  for (;;) {
    const ok = await pollOnce();
    if (ok && fails >= 2) {
      backUntil = Date.now() + BACK_MS; clearTimeout(backTimer); backTimer = setTimeout(paintConn, BACK_MS + 50);
    }
    if (ok) { fails = 0; failingSince = 0; } else { fails += 1; failingSince = failingSince || Date.now(); }
    paintConn();
    const delay = ok ? 800 : [1000, 2000, 5000][Math.min(fails, 3) - 1];
    await new Promise(r => { wake = r; setTimeout(r, delay); });
    wake = null;
  }
}
$("retry").onclick = () => { if (connDown) { if (wake) wake(); } else if (unsent) sendWav(unsent); };

// ---- the floor: one call talks at a time ----------------------------------
// Pressing Talk, sending text or playing an answer takes the floor for this call. Every other call's
// page then pauses its voice and stops its recording, and this page does the same when another call
// takes it. Pages in this browser hear it at once on a BroadcastChannel; a page on another device
// hears it on its next poll. floorN is the count of floor changes this page has seen; floorEpoch
// counts the takes made here, so a poll that left before a take cannot undo it.
let floorN = 0, floorEpoch = 0, heardSent = null;
const floorChannel = "BroadcastChannel" in window ? new BroadcastChannel("talk-floor") : null;
let floorTakenAt = -Infinity;
const FLOOR_CROSS_MS = 2000;
function takeFloor(heard) {
  const epoch = ++floorEpoch;
  floorTakenAt = performance.now();
  if (floorChannel) floorChannel.postMessage({call: CFG.call});
  api("/api/floor", {method: "POST", body: JSON.stringify(heard == null ? {} : {heard}), headers: {"Content-Type": "application/json"}})
    .then(r => r.ok ? r.json() : null).then(b => { if (b && epoch === floorEpoch) { floorN = b.floor_n; if (wake) wake(); } }).catch(() => {});
}
function topicOf(id) { const c = (view.calls || []).find(x => x.id === id); return c ? c.topic : ""; }
function yieldFloor(id) {
  const busyHere = !audio.paused || !!recorder || listening();
  if (!audio.paused) audio.pause();
  if (recorder) { stopRecording(); setMode("idle"); }
  if (live) parkLive("floor");
  if (busyHere) { const t = topicOf(id); showError("Paused: you are talking in " + (t ? "“" + t + "”" : "another call") + "."); }
}
// Two calls that hear one voice claim the floor at once, and each hears the other's claim. Yielding to
// it here would leave neither listening; the server keeps the later claim, and the next poll yields.
if (floorChannel) floorChannel.onmessage = ev => {
  const id = ev.data && ev.data.call;
  if (id && id !== CFG.call && performance.now() - floorTakenAt > FLOOR_CROSS_MS) yieldFloor(id);
};
audio.addEventListener("play", () => {
  if (current && (current.id !== heardSent || view.floor_call !== CFG.call)) { heardSent = current.id; takeFloor(current.id); }
});

// The other calls open on this machine: a new answer in one shows as a dot on the pill's button.
function callState(c) {
  if (c.unheard) return c.unheard === 1 ? "new answer" : c.unheard + " new answers";
  if (c.ended) return "ended";
  if (c.working) return "working";
  return c.floor ? "talking now" : "open";
}
function paintCalls() {
  const list = view.calls || [], nav = $("calls");
  const sig = JSON.stringify(list.map(c => [c.id, c.topic, callState(c)]));
  if (nav.dataset.sig === sig) return;
  nav.dataset.sig = sig;
  const rows = list.map(c => {
    const a = document.createElement("a"); a.href = "/c/" + encodeURIComponent(c.id);
    a.className = "callrow" + (c.unheard ? " new" : "") + (c.ended ? " ended" : "");
    const dot = document.createElement("span"); dot.className = "live";
    const t = document.createElement("span"); t.className = "t"; t.textContent = c.topic;
    const s = document.createElement("span"); s.className = "s"; s.textContent = callState(c);
    a.title = c.topic + " · " + callState(c); a.append(dot, t, s); return a;
  });
  const all = document.createElement("a"); all.href = "/"; all.className = "callrow all"; all.textContent = "All calls";
  nav.replaceChildren(...rows, all);
}

// ---- the audio being made -----------------------------------------------
// An answer is read aloud in one piece, so it plays without a pause between sentences. Until its
// audio is ready, a bar in the panel's foot fills toward the server's estimate of how long it takes,
// and holds short of the end until the audio is there.
let clockSkew = 0, prepTimer = 0;
function prepShare(e) {
  if (e.speech !== "making" || !e.speech_started || !e.speech_estimate) return 0;
  const f = (Date.now() / 1000 + clockSkew - e.speech_started) / e.speech_estimate;
  return f < 0.9 ? Math.max(0, f) : 0.9 + 0.08 * (1 - Math.exp(-(f - 0.9) * 2));
}
function paintPrep(e) {
  const on = !!e && (e.speech === "pending" || e.speech === "making");
  $("prep").hidden = !on;
  if (on) {
    const share = prepShare(e), left = e.speech === "making" ? e.speech_estimate * (1 - share / 0.98) : 0;
    $("prepfill").style.width = (100 * share).toFixed(1) + "%";
    $("prepfill").parentElement.classList.toggle("queued", e.speech === "pending");
    $("preplbl").textContent = e.speech === "pending" ? "Waiting for the voice…"
      : share < 0.9 && left >= 1.5 ? "Preparing the voice · about " + Math.ceil(left) + " s" : "Preparing the voice · almost ready";
  }
  if (on && !prepTimer) prepTimer = setInterval(() => paintPrep(shownAnswer()), 200);
  else if (!on && prepTimer) { clearInterval(prepTimer); prepTimer = 0; }
}

// ---- the player --------------------------------------------------------
function audioUrl(path) { return location.pathname.replace(/\/$/, "") + "/" + path; }
function setSrc(path) { const url = audioUrl(path); if (audio.dataset.src !== url) { audio.src = url; audio.dataset.src = url; } }
function load(e, play) {
  current = e; cueSync = true;
  setSrc(e.audio);
  audio.playbackRate = speed; audio.preservesPitch = true;
  // A pause before playback starts (another call took the floor) rejects with AbortError: not a block.
  if (play) audio.play().catch(err => { if (!err || err.name !== "AbortError") showError("The browser blocked playback. Press Play."); });
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({title: "Answer " + (e.n || ""), artist: "Claude", album: CFG.topic});
  paintNow(); paintAll();
}
function maybeAutoplay() {
  const fresh = view.entries.filter(e => e.who === "claude" && e.speech === "ready" && !seen.has(e.id));
  if (!fresh.length) return;
  for (const e of fresh) seen.add(e.id);
  const last = fresh[fresh.length - 1];
  // An answer the user has already spoken or typed past (its voice was still being made) never starts by
  // itself: it would play the old board after they moved on, and hold the player from the newer answer.
  const at = view.entries.findIndex(e => e.id === last.id);
  if (view.entries.slice(at + 1).some(e => e.who === "you" && !e.withdrawn)) return;
  // Only the call the user is talking in reads new answers aloud; another call's wait, marked new.
  const mine = !view.floor_call || view.floor_call === CFG.call;
  if (userBusy()) { if (mine && autoplay) deferred = last; return; }  // played once they are done (settle)
  if (current && !audio.paused && !audio.ended) return;
  // A tab out of sight never starts talking: the answer waits in the player and plays when the tab is back.
  const away = document.visibilityState === "hidden";
  hiddenHeld = away && autoplay && !recorder && mine ? last.id : null;
  load(last, autoplay && !recorder && mine && !away);
}
let hiddenHeld = null;      // the id of a new answer that came while the tab was hidden: it plays when the tab is seen
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible" || hiddenHeld === null) return;
  const id = hiddenHeld; hiddenHeld = null;
  if (current && current.id === id && audio.paused && !audio.ended && audio.currentTime === 0 && !userBusy() && !recorder) {
    audio.play().catch(() => {});
  }
});
// ---- the word being said ------------------------------------------------
function playFrom(e, t) {
  // Play the answer from time `t` seconds in.
  e = view.entries.find(x => x.id === e.id) || e;
  if (e.speech !== "ready") return;
  toVoice();
  load(e, false); audio.currentTime = t;
  audio.playbackRate = speed; audio.play().catch(() => {});
}
function wordAt(e, t) {
  // The last word that has started by time t, or -1.
  let lo = 0, hi = e.words.length - 1, k = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (e.words[m][2] <= t) { k = m; lo = m + 1; } else hi = m - 1; }
  return k;
}
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
      syncStage(e, lead >= 0 ? e.words[lead][0] : -1);
    }
  }
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

// ---- the board follows the voice ------------------------------------------
const LEAD_S = 0.12;
let cueSync = true, sent = null;
function stateAt(e, pos) {
  // Before its first cue the answer's first board is in front: the one it put up as it arrived.
  const cues = e.cues || [], st = {front: cues.find(c => c.kind === "front")?.view ?? null, frames: {}, key: null};
  for (const c of cues) if (c.kind === "frame") st.frames[c.view] = 0;
  let lo = 0, hi = cues.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (cues[m].at <= pos) lo = m + 1; else hi = m; }
  for (const c of cues.slice(0, lo)) {
    if (c.kind === "key") st.key = c;
    else { st.front = c.view; if (c.kind === "frame") st.frames[c.view] = c.n; }
  }
  return st;
}
function syncStage(e, pos) {
  const st = stateAt(e, pos);
  if (cueSync || !sent || sent.id !== e.id) {
    toStage({type: "stage:state", front: st.front, frames: st.frames, keys: st.key ? st.key.index : 0, answer: e.n || null});
  } else {
    if (st.front && st.front !== sent.front) toStage({type: "stage:front", view: st.front, manual: false, answer: e.n || null});
    for (const [view, n] of Object.entries(st.frames)) {
      if (sent.frames[view] !== n) toStage({type: "stage:frame", view, n, animate: n === sent.frames[view] + 1, answer: e.n || null});
    }
    if (st.key && (!sent.key || st.key.at !== sent.key.at || st.key.index !== sent.key.index)) toStage({type: "stage:key", view: st.key.view, index: st.key.index});
  }
  cueSync = false;
  sent = {id: e.id, ...st};
}
function resync() { cueSync = true; highlight(); }
// A play the reader starts takes the board back to the voice: following turns on (a tab, a chip or a step
// by hand turned it off), and the next frame sends the whole picture.
function toVoice() {
  cueSync = true;
  if (!follow) { follow = true; toStage({type: "stage:follow", on: true}); paintSettings(); }
}
// An answer played to its end holds its last frame a moment, then each of its boards shows whole, undimmed.
const REST_HOLD_MS = 1500;
let restTimer = 0;
function restBoards(e) {
  const views = [...new Set((e.cues || []).filter(c => c.kind === "frame").map(c => c.view))];
  if (views.length) toStage({type: "stage:rest", views, answer: e.n || null});
}
let failedShown = null;
function showFailedAnswer() {
  const e = lastAnswer();
  if (!e || e.speech !== "failed" || failedShown === e.id) return;
  failedShown = e.id; cueSync = true; syncStage(e, Infinity); restBoards(e);  // no voice to hold for
}
let answerSent = null;
audio.addEventListener("play", () => {
  if (current && current.id !== answerSent) { answerSent = current.id; toStage({type: "stage:answer", n: current.n || 0}); }
});
// The frame loop runs only while audio plays; a pause, an end or a seek while paused paints once.
let raf = 0;
function frame() { raf = 0; highlight(); if (!audio.paused) raf = requestAnimationFrame(frame); }
function startHighlight() { if (!raf) raf = requestAnimationFrame(frame); }
function stopHighlight() { if (raf) cancelAnimationFrame(raf); raf = 0; highlight(); }
audio.addEventListener("ended", () => {
  if (!current) return;
  const e = view.entries.find(x => x.id === current.id) || current;
  syncStage(e, Infinity);
  clearTimeout(restTimer);
  restTimer = setTimeout(() => { if (current && current.id === e.id && audio.ended) restBoards(e); }, REST_HOLD_MS);
});
audio.addEventListener("seeking", () => { cueSync = true; });
function skip(by) { audio.currentTime = Math.min(Math.max(0, audio.currentTime + by), audio.duration || 0); paintPill(); }
// Play plays the board in front. When the voice is not on it (it came from an earlier answer, or this
// answer has moved past it), Play plays that board's explanation, from the sentence it came in with,
// and the board unfolds again; otherwise Play pauses and resumes. A board no answer explains (a page,
// the key points) leaves Play as it is.
function boardStart() {
  if (!frontBoard || (!audio.paused && !audio.ended)) return null;
  const n = boardAnswer.get(frontBoard);
  const e = n ? view.entries.find(x => x.who === "claude" && x.n === n) : null;
  if (!e || e.speech !== "ready" || !e.words || !e.words.length) return null;
  const cue = (e.cues || []).find(c => c.view === frontBoard);
  if (!cue) return null;
  const onIt = current && current.id === e.id && !audio.ended && stateAt(e, wordCharAt(e, audio.currentTime)).front === frontBoard;
  if (onIt) return null;
  const w = e.words.find(w => w[0] >= cue.at) || e.words[e.words.length - 1];
  return {e, t: cue.at === 0 ? 0 : w[2]};
}
function wordCharAt(e, t) { const k = wordAt(e, t); return k < 0 ? -1 : e.words[k][0]; }
function togglePlay() {
  release();
  const b = boardStart();
  if (b) { playFrom(b.e, b.t); return; }
  if (!current) { const e = lastAnswer(); if (e) { toVoice(); load(e, true); } return; }
  if (audio.paused) { toVoice(); audio.play().catch(() => {}); } else audio.pause();
}
$("playpause").onclick = $("railpp").onclick = togglePlay;
$("back").onclick = $("railback").onclick = () => skip(-10);
$("seek").oninput = () => { audio.currentTime = Number($("seek").value); paintPill(); };
for (const s of SPEEDS) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.speed = s; b.textContent = s + "×";
  b.onclick = () => { speed = s; store.set("speed", s); audio.playbackRate = s; paintSettings(); };
  $("speeds").append(b);
}
$("autoplay").onclick = () => { autoplay = !autoplay; store.set("autoplay", autoplay); paintSettings(); };
for (const ev of ["play", "pause", "ended", "durationchange", "loadedmetadata"]) audio.addEventListener(ev, paintAll);
audio.addEventListener("timeupdate", paintPill);
for (const ev of ["play", "pause", "ended"]) audio.addEventListener(ev, paintNow);
audio.addEventListener("play", startHighlight);
for (const ev of ["pause", "ended"]) audio.addEventListener(ev, stopHighlight);
audio.addEventListener("seeked", () => { if (audio.paused) highlight(); });
// ---- the keyboard: Space pauses and plays, ← and → move by a sentence ------------------
// An answer's sentence starts, in seconds: its first word and every word after one that ends a sentence.
function sentenceTimes(e) {
  if (!e.words || !e.words.length) return null;
  const out = [e.words[0][2]];
  for (let i = 1; i < e.words.length; i++) {
    if (/[.!?…][)\]"'”’]*$/.test(e.text.slice(e.words[i - 1][0], e.words[i - 1][1]))) out.push(e.words[i][2]);
  }
  return out;
}
const AGAIN_S = 1.0;   // ← this soon after a sentence starts goes to the one before, as a player's previous track does
const SKIP_S = 5;      // an answer with no word timings moves by this much instead
function jump(dir) {
  if (!current) return;
  const e = view.entries.find(x => x.id === current.id) || current, t = audio.currentTime || 0;
  const starts = sentenceTimes(e);
  if (!starts) { skip(dir * SKIP_S); return; }
  let to;
  if (dir < 0) {
    const i = starts.findLastIndex(s => s <= t + 0.05);
    to = i < 0 ? 0 : i > 0 && t - starts[i] < AGAIN_S * (audio.playbackRate || 1) ? starts[i - 1] : starts[i];
  } else to = starts.find(s => s > t + 0.05) ?? (audio.duration || t);
  cueSync = true;
  audio.currentTime = to; paintPill();
  if (audio.paused) highlight();
}
// The keys steer the answer wherever nothing is being typed: on this page, on the stage (which
// passes them on as stage:key), and in the text field while it is empty. False: the key was not used.
function mediaKey(key) {
  if (recorder || openPop || (busy && talkMode !== "live")) return false;
  if (key === " ") {
    const e = shownAnswer();
    if (!current && !(e && e.speech === "ready")) return false;
    togglePlay(); return true;
  }
  if (!current) return false;
  jump(key === "ArrowLeft" ? -1 : 1); return true;
}
const MEDIA_KEYS = new Set([" ", "ArrowLeft", "ArrowRight"]);
document.addEventListener("keydown", ev => {
  if (!MEDIA_KEYS.has(ev.key) || ev.ctrlKey || ev.metaKey || ev.altKey || ev.shiftKey) return;
  const at = document.activeElement;
  const free = !at || at === document.body || (at === $("text") && !$("text").value)
    || (at.tagName === "BUTTON" && !!at.closest("#panel"));
  if (!free) return;
  if (ev.key === " " && ev.repeat) { ev.preventDefault(); return; }
  if (mediaKey(ev.key)) ev.preventDefault();
});
if ("mediaSession" in navigator) {
  const ms = navigator.mediaSession;
  ms.setActionHandler("play", () => { toVoice(); audio.play(); }); ms.setActionHandler("pause", () => audio.pause());
  ms.setActionHandler("seekbackward", d => skip(-(d.seekOffset || 10))); ms.setActionHandler("seekforward", d => skip(d.seekOffset || 10));
}

// ---- talking -----------------------------------------------------------
const LANG_NAMES = {auto: "Auto", en: "English", el: "Ελληνικά"};
for (const code of CFG.languages) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.lang = code;
  b.textContent = LANG_NAMES[code] || code.toUpperCase();
  b.onclick = () => { language = code; store.set("language", code); paintSettings(); };
  $("lang").append(b);
}
const BARS = 28, levels = new Array(BARS).fill(0);
$("bars").append(...Array.from({length: BARS}, () => document.createElement("i")));
let meterRaf = 0;
function paintMeter() {
  meterRaf = 0;
  const bars = $("bars").children;
  if (!reduced.matches) for (let i = 0; i < BARS; i++) bars[i].style.height = (4 + levels[i] * 28) + "px";
  $("app").style.setProperty("--lvl", levels[BARS - 1].toFixed(2));
}
function setMode(mode) {
  busy = mode === "busy";
  if (mode !== "recording") { levels.fill(0); $("app").style.removeProperty("--lvl"); }
  paintAll();
}

async function startRecording() {
  if (starting) return;
  showPop(null);
  showError("");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showError("This page cannot reach a microphone. Open it over https or on localhost."); return; }
  let stream;
  starting = true;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}}); }
  catch (err) { showError("No microphone: " + err.message); return; }
  finally { starting = false; }
  if (recorder) { stream.getTracks().forEach(t => t.stop()); return; }
  takeFloor(null);
  audio.pause();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  node.onaudioprocess = ev => {
    const d = ev.inputBuffer.getChannelData(0); chunks.push(new Float32Array(d));
    let peak = 0; for (let i = 0; i < d.length; i += 16) peak = Math.max(peak, Math.abs(d[i]));
    levels.push(Math.min(1, peak * 1.6)); levels.shift();
    if (!meterRaf) meterRaf = requestAnimationFrame(paintMeter);
  };
  source.connect(node); node.connect(ctx.destination);
  const started = Date.now();
  const timer = setInterval(() => $("rectime").textContent = fmt((Date.now() - started) / 1000), 250);
  recorder = {stream, ctx, source, node, chunks, timer};
  $("rectime").textContent = "0:00"; setMode("recording");
}

function stopRecording() {
  const r = recorder; recorder = null;
  clearInterval(r.timer); r.node.disconnect(); r.source.disconnect();
  r.stream.getTracks().forEach(t => t.stop()); r.ctx.close();
  return r;
}

function toWav(chunks, rate) {
  const total = chunks.reduce((n, c) => n + c.length, 0), all = new Float32Array(total);
  let at = 0; for (const c of chunks) { all.set(c, at); at += c.length; }
  const ratio = rate / 16000, n = Math.floor(total / ratio), pcm = new Int16Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), b = Math.min(total, Math.max(a + 1, Math.floor((i + 1) * ratio)));
    let sum = 0; for (let j = a; j < b; j++) sum += all[j];
    const v = Math.max(-1, Math.min(1, sum / (b - a))); pcm[i] = v < 0 ? v * 0x8000 : v * 0x7FFF;
  }
  const buf = new ArrayBuffer(44 + pcm.byteLength), dv = new DataView(buf);
  const str = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); dv.setUint32(4, 36 + pcm.byteLength, true); str(8, "WAVE"); str(12, "fmt ");
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, 16000, true);
  dv.setUint32(28, 32000, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, "data"); dv.setUint32(40, pcm.byteLength, true);
  new Int16Array(buf, 44).set(pcm);
  return new Blob([buf], {type: "audio/wav"});
}

async function sendRecording() {
  const r = stopRecording();
  await sendWav(toWav(r.chunks, r.ctx.sampleRate));
}

// While the server restarts (503, or no answer at all) the recording is sent again until the next
// server takes it, for up to three minutes. A recording still not taken is kept for Send again.
async function sendWav(wav) {
  unsent = null;
  setMode("busy");
  const until = Date.now() + 180000;
  for (let wait = 1000; ; wait = Math.min(wait * 2, 8000)) {
    let resp = null, failed = "";
    try { resp = await api("/api/listen?lang=" + language, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}}); }
    catch (err) { failed = err.message; }
    if (resp && resp.status !== 503) {
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) { if (![410, 413].includes(resp.status)) unsent = wav; showError(body.error || "Sending failed: HTTP " + resp.status); }
      else if (!body.text) showError("Nothing was heard. Try again, a little closer to the microphone.");
      view.v = -1;
      break;
    }
    if (Date.now() > until) { unsent = wav; showError("Sending failed: " + (failed || "the talk server is restarting")); break; }
    errText = "Reconnecting… your recording is kept and will be sent."; paintToast();
    await new Promise(ok => setTimeout(ok, wait));
  }
  if (errText.startsWith("Reconnecting…")) showError("");
  setMode("idle");
}

async function sendText() {
  const text = $("text").value.trim(); if (!text) return;
  $("sendtext").disabled = true;
  takeFloor(null);
  try {
    const resp = await api("/api/say", {method: "POST", body: JSON.stringify({text}), headers: {"Content-Type": "application/json"}});
    const body = await resp.json().catch(() => ({}));
    // What you send moves the call on: the answer still playing stops, so the reply plays when it comes,
    // as it does when you press Talk.
    if (resp.ok) { $("text").value = ""; fitText(); release(); if (!audio.paused) audio.pause(); view.v = -1; }
    else showError(body.error || "Sending failed: HTTP " + resp.status);
  } catch (err) { showError("Sending failed: " + err.message); }
  $("sendtext").disabled = !$("text").value.trim();
}
// The text field grows with what is typed, up to a few lines, and Send waits for something to send.
function fitText() {
  const t = $("text"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px";
  $("sendtext").disabled = !t.value.trim();
}
$("text").addEventListener("input", fitText);
$("text").placeholder = "Type, or press the mic";
// Typing is as direct as talking: a key pressed anywhere on the page goes to the text field.
document.addEventListener("keydown", ev => {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1 || openPop || recorder || view.ended) return;
  if (document.activeElement && document.activeElement !== document.body) return;
  $("text").focus();
});

// ---- live mode: the microphone stays open --------------------------------------------
// A loudness detector notices speech, keeping the moment before it so the first syllable is kept, and
// sends it after a pause. Only voiced time counts, against a noise floor that follows the room.
// Speech over an answer holds it (`held`): with "By talking" the voice drops at once and stops after
// LIVE.pauseMs of real speech; with cue words it plays on unless the words start with "wait",
// "listen" and the like, and a cue alone stops it and waits. Whatever was said settles the hold: a
// turn leaves the answer stopped, nothing (a cough, "mm-hm", its own echo) resumes it from the start
// of its sentence. One page listens per call and one call per browser: the others park.
const LIVE = {chunk: 2048, preMs: 400, minRms: 0.012, startMs: 160, startOverMs: 320, overGain: 1.8, minSpeechMs: 350,
              floorMs: 8000, pauseMs: 700, duck: 0.2, maxMs: 60000, hardMs: 420000, armedMs: 6000, sleepMs: 600000};
const liveQueue = [];
let liveSending = false, wokeAt = 0;
const PAGE_ID = Math.random().toString(36).slice(2);
const liveChannel = "BroadcastChannel" in window ? new BroadcastChannel("talk-live") : null;
const listening = () => !!live && !live.suspended && !live.parked;
// The user is talking, or what they said is on its way: new answers wait and the held answer stays held.
const userBusy = () => !!held || !!(live && live.speech) || liveQueue.length > 0 || liveSending;
const later = ms => new Promise(ok => setTimeout(ok, ms));

async function startLive() {
  if (live || view.ended) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showError("This page cannot reach a microphone. Open it over https or on localhost."); return; }
  let stream;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}}); }
  catch (err) { showError("No microphone: " + err.message); return; }
  if (live || talkMode !== "live" || view.ended) { stream.getTracks().forEach(t => t.stop()); return; }
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream), node = ctx.createScriptProcessor(LIVE.chunk, 1, 1);
  live = {stream, ctx, source, node, rate: ctx.sampleRate, recent: [], pre: [], loud: 0, quiet: 0, voiced: 0, ms: 0,
          speech: false, chunks: [], floorTaken: false, parked: null, lastVoice: performance.now(),
          suspended: ctx.state === "suspended"};
  node.onaudioprocess = ev => liveChunk(new Float32Array(ev.inputBuffer.getChannelData(0)));
  source.connect(node); node.connect(ctx.destination);
  const track = stream.getAudioTracks()[0];
  if (track) track.onended = () => { if (live && live.stream === stream) stopLive("The microphone was lost. Press the mic to listen again."); };
  liveNote = "";
  claimLive();
}
function stopLive(note = "") {
  const l = live; live = null;
  if (!l) return;
  l.node.disconnect(); l.source.disconnect(); l.stream.getTracks().forEach(t => t.stop()); l.ctx.close();
  levels.fill(0); $("app").style.removeProperty("--lvl");
  liveQueue.length = 0;           // said but not yet sent: dropped with the microphone
  liveNote = note;
  if (held) held.armed = false;
  settle();                       // an answer the speech was holding goes on
  paintAll();
}
// Chrome starts audio only after a click or key on the page. A click in the stage lands in its frame,
// and shows here only as this window losing focus.
function wakeLive() {
  if (!live || !live.suspended) return;
  wokeAt = performance.now();
  live.ctx.resume().then(() => { if (live && live.ctx.state === "running") { live.suspended = false; paintAll(); } }).catch(() => {});
}
document.addEventListener("pointerdown", wakeLive, true);
document.addEventListener("keydown", wakeLive, true);
window.addEventListener("blur", wakeLive);
// This page listens: other pages of this call stop (a TV and a laptop both open), and other calls yield
// the floor (one voice is never sent to two calls).
let claimedAt = 0;
function claimLive() {
  if (!live) return;
  live.parked = null;
  claimedAt = Date.now();
  if (liveChannel) liveChannel.postMessage({call: CFG.call, page: PAGE_ID, at: claimedAt});
  if (view.floor_call && view.floor_call !== CFG.call) takeFloor(null);
  paintAll();
}
function parkLive(why) {
  if (!live) return;
  if (live.speech) { live.speech = false; live.chunks = []; }
  live.parked = why;
  settle(); paintAll();
}
if (liveChannel) liveChannel.onmessage = ev => {
  const m = ev.data || {};
  // Only a newer claim parks this page, the page id breaking a tie: two pages claiming at once never
  // both stand down.
  const newer = m.at > claimedAt || (m.at === claimedAt && String(m.page) > PAGE_ID);
  if (m.call === CFG.call && m.page !== PAGE_ID && live && !live.parked && newer) parkLive("screen");
};
// Coming back to this page (a tab, a window, the TV's input) is the user choosing to talk here.
window.addEventListener("focus", () => { if (live && live.parked) claimLive(); });
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && live && live.parked) claimLive(); });

// The character the voice has reached in the answer being played: how far the user heard.
function heardAt() {
  const e = current && (view.entries.find(x => x.id === current.id) || current);
  if (!e || !e.words || !e.words.length) return 0;
  const k = wordAt(e, audio.currentTime);
  return k < 0 ? 0 : e.words[k][1];
}
// Where an interrupted answer picks up again: the start of the sentence it was in.
function sentenceStart() {
  const e = current && (view.entries.find(x => x.id === current.id) || current), t = audio.currentTime || 0;
  const starts = e && sentenceTimes(e);
  if (!starts) return Math.max(0, t - 2);
  const i = starts.findLastIndex(s => s <= t + 0.05);
  return i < 0 ? 0 : starts[i];
}
function liveChunk(d) {
  const l = live;
  if (!l || l.suspended) return;
  let sum = 0; for (let i = 0; i < d.length; i++) sum += d[i] * d[i];
  const lvl = Math.sqrt(sum / d.length), ms = d.length / l.rate * 1000, now = performance.now();
  levels.push(Math.min(1, lvl * 8)); levels.shift();
  if (!meterRaf) meterRaf = requestAnimationFrame(paintMeter);
  if (l.parked) return;
  // The floor is the quietest moment of the last few seconds: a fan or music switched on raises it,
  // so a louder room never reads as speech that does not end.
  l.recent.push(lvl); if (l.recent.length * ms > LIVE.floorMs) l.recent.shift();
  const over = !!held || (!!current && !audio.paused);
  const thr = Math.max(LIVE.minRms, Math.min(...l.recent) * 3) * (over ? LIVE.overGain : 1);
  if (!l.speech) {
    l.pre.push(d); if (l.pre.length * ms > LIVE.preMs) l.pre.shift();
    if (lvl > thr) { l.loud += ms; if (l.loud >= (over ? LIVE.startOverMs : LIVE.startMs)) speechStarts(); }
    else l.loud = 0;
    if (now - l.lastVoice > LIVE.sleepMs && !userBusy() && !busy) stopLive("Asleep after 10 minutes of quiet. Press the mic to listen.");
    return;
  }
  l.chunks.push(d); l.ms += ms;
  if (lvl >= thr * 0.7) { l.voiced += ms; l.quiet = 0; l.lastVoice = now; } else l.quiet += ms;
  if (!l.floorTaken && l.voiced >= LIVE.minSpeechMs) {   // a cough never takes the floor from another call
    l.floorTaken = true;
    if (view.floor_call !== CFG.call) takeFloor(null);
  }
  if (held && held.ducked && !held.paused && l.voiced >= LIVE.pauseMs) { audio.pause(); held.paused = true; paintAll(); }
  // A long turn is cut only at a pause in it, past the cap; the hard cap keeps the recording under the server's limit.
  if (l.quiet >= endPause || (l.ms >= LIVE.maxMs && l.quiet > 0) || l.ms >= LIVE.hardMs) speechEnds();
}
function speechStarts() {
  const l = live;
  // The loud run that started the speech is speech already: it counts as voiced time.
  l.speech = true; l.chunks = l.pre.splice(0); l.ms = l.loud; l.voiced = l.loud; l.quiet = 0; l.loud = 0; l.floorTaken = false;
  l.lastVoice = performance.now();
  if (held && held.armed) { clearTimeout(held.armTimer); held.armTimer = 0; }   // the question after a cue word
  else if (!held && current && !audio.paused) {
    held = {id: current.id, at: heardAt(), from: sentenceStart(), ducked: false, paused: false, armed: false, armTimer: 0};
  }
  if (held && barge === "talk" && !held.ducked && !held.paused && !audio.paused) { audio.volume = LIVE.duck; held.ducked = true; }
  paintAll();
}
function speechEnds() {
  const l = live;
  const u = {chunks: l.chunks, rate: l.rate, over: held ? {id: held.id, at: held.at} : null,
             gate: barge === "keyword" && !!held && !held.armed};
  const voiced = l.voiced;
  l.speech = false; l.chunks = []; l.ms = 0; l.voiced = 0; l.quiet = 0;
  if (voiced < LIVE.minSpeechMs) { settle(); return; }   // a click or a breath: nothing to send
  liveQueue.push(u); paintAll(); drainLive();
}
async function drainLive() {
  if (liveSending) return;
  liveSending = true;
  while (liveQueue.length) await sendLive(liveQueue.shift());
  liveSending = false;
  settle();
}
// What happens to a held answer once nothing more is being said or sent: a newer answer plays, else the
// held one picks up from the start of its sentence. An answer that was stopped for a question is not held.
function settle() {
  if ((live && live.speech) || liveQueue.length || liveSending || (held && held.armed)) return;
  const h = held; held = null;
  audio.volume = 1;
  if (deferred) { const e = deferred; deferred = null; load(view.entries.find(x => x.id === e.id) || e, true); return; }
  if (h && h.paused && current && current.id === h.id) { audio.currentTime = h.from; audio.play().catch(() => {}); }
  paintAll();
}
// The user took the player in hand (Space, a button): whatever speech was holding lets go of it.
function release() {
  if (!held) return;
  clearTimeout(held.armTimer); held = null; audio.volume = 1;
}
// A soft tone in the headphones: a higher one when a cue word stopped the answer, a lower one when a turn went.
function chime(freq) {
  const ctx = live && live.ctx;
  if (!ctx || ctx.state !== "running") return;
  const o = ctx.createOscillator(), g = ctx.createGain();
  o.frequency.value = freq; g.gain.setValueAtTime(0.0001, ctx.currentTime);
  g.gain.exponentialRampToValueAtTime(0.05, ctx.currentTime + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.18);
  o.connect(g); g.connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.2);
}
function flash(text) { liveFlash = {text, until: Date.now() + 2500}; setTimeout(paintAll, 2600); }
async function sendLive(u) {
  const q = new URLSearchParams({lang: language, live: "1"});
  if (u.over) { q.set("interrupted", u.over.id); q.set("at", u.over.at); }
  if (u.gate) q.set("keyword", "1");
  if (!u.gate) { busy = true; paintAll(); }
  const wav = toWav(u.chunks, u.rate);
  let body = null;
  // A restarting server (503) or a dropped connection is tried again for a while; what still does not
  // go is kept for Send again, as a recording is in Press to talk.
  for (let tries = 0; ; tries++) {
    try {
      const resp = await api("/api/listen?" + q, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}});
      if (resp.status === 503 && tries < 5) { await later(1000 * 2 ** tries); continue; }
      const got = await resp.json().catch(() => ({}));
      if (resp.ok) body = got;
      else { showError(got.error || "Sending failed: HTTP " + resp.status); if (![410, 413].includes(resp.status) && !u.gate) unsent = wav; }
    } catch (err) {
      if (tries < 3) { await later(1000 * 2 ** tries); continue; }
      showError("Sending failed: " + err.message); if (!u.gate) unsent = wav;
    }
    break;
  }
  busy = false;
  if (body && body.command) {
    runCommand(body.command, body);
  } else if (body && body.held) {
    // A thought left hanging ("so what about the… um"): the server waits for its end, so a turn is coming.
    if (held) { audio.pause(); clearTimeout(held.armTimer); held = null; }
    audio.volume = 1; deferred = null;
  } else if (body && body.keyword) {
    // A cue word alone: the answer stops where it was, and what is said next is the question.
    if (held) {
      audio.pause(); held.paused = true; held.armed = true; audio.volume = 1;
      held.armTimer = setTimeout(() => { if (held && held.armed && !(live && live.speech)) { held.armed = false; settle(); } }, LIVE.armedMs);
    }
    chime(880);
  } else if (body && body.entry) {
    if (held) { audio.pause(); clearTimeout(held.armTimer); held = null; }
    audio.volume = 1; deferred = null;
    chime(520);
    undoable = {entry: body.entry.id, until: Date.now() + 8000}; setTimeout(paintAll, 8100);
    turnSentAt = Date.now();
    view.v = -1; if (wake) wake();
  } else if (body && !body.ignored && !u.over) flash("Didn't catch that.");
  paintAll();
}
// A spoken command, acted on here: no turn, no wait for Claude.
function runCommand(cmd, body) {
  chime(700);
  if (cmd === "mute") { stopLive("Stopped listening. Press the mic to listen."); return; }
  if (cmd === "withdraw") { undoable = null; flash("Taken back."); if (held) { held.armed = false; } return; }  // settle resumes a held answer
  const h = held;
  release();
  if (cmd === "pause") { audio.pause(); return; }
  toVoice();  // resume, repeat and back all play
  if (!current) { const e = lastAnswer(); if (e && e.speech === "ready") load(e, true); return; }
  if (cmd === "resume") { if (h && h.paused) audio.currentTime = h.from; audio.play().catch(() => {}); return; }
  if (cmd === "repeat") { audio.currentTime = h ? h.from : sentenceStart(); audio.play().catch(() => {}); return; }
  if (cmd === "back") { if (h) audio.currentTime = h.from; jump(-1); audio.play().catch(() => {}); }
}
$("undo").onclick = async () => {
  const u = undoable; undoable = null; paintAll();
  if (!u) return;
  try {
    const r = await api("/api/withdraw", {method: "POST", body: JSON.stringify({entry: u.entry}), headers: {"Content-Type": "application/json"}});
    const b = await r.json().catch(() => ({}));
    flash(b.withdrawn ? "Taken back." : "Too late: Claude already has it.");
    view.v = -1; if (wake) wake();
  } catch { showError("Undo failed: the call server did not answer."); }
};
// "One moment.": once per live turn, when Claude has worked a few seconds and nothing is playing.
const fillerAudio = new Audio();
setInterval(() => {
  if (talkMode !== "live" || !view.filler || !turnSentAt || fillerFor === turnSentAt) return;
  if (!view.working || Date.now() - turnSentAt < 3000 || !audio.paused || userBusy()) return;
  fillerFor = turnSentAt;
  fillerAudio.src = audioUrl(view.filler); fillerAudio.volume = 0.8; fillerAudio.play().catch(() => {});
}, 500);
for (const b of $("screen").children) b.onclick = () => {
  screenMode = b.dataset.choice; store.set("screen", screenMode);
  toStage({type: "stage:zoom", zoom: screenMode === "tv" ? TV_ZOOM : 1}); paintAll();
};
function setTalkMode(mode) {
  talkMode = mode; store.set("talkMode", mode);
  if (mode === "live") { if (recorder) sendRecording(); startLive(); }   // an open recording goes first, once
  else stopLive();
  paintAll();
}
for (const b of $("tmode").children) b.onclick = () => setTalkMode(b.dataset.choice);
for (const b of $("barge").children) b.onclick = () => { barge = b.dataset.choice; store.set("barge", barge); paintSettings(); };
for (const b of $("endpause").children) b.onclick = () => { endPause = +b.dataset.choice; store.set("endPause", endPause); paintSettings(); };

// In live mode the mic button is the switch for listening. While Chrome holds the audio back it starts
// it, and the same press must not then switch listening off.
function liveButton() {
  if (live && (live.suspended || performance.now() - wokeAt < 1000)) { wakeLive(); return; }
  if (live && live.parked) { claimLive(); return; }
  if (live) stopLive(); else startLive();
}
$("talk").onclick = $("railtalk").onclick = () => talkMode === "live" ? liveButton() : recorder ? sendRecording() : startRecording();
$("send").onclick = sendRecording;
$("cancel").onclick = () => { stopRecording(); setMode("idle"); };
$("sendtext").onclick = sendText;
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendText(); } });
// The stage demo, the call's tutorial: the tab opens at once (a tab opened after the server answers would
// be blocked as a pop-up), then goes to the demo call the server keeps ready.
$("demo").hidden = !!CFG.demo;  // the demo's own page needs no button to itself
$("demo").onclick = async () => {
  const tab = window.open("", "_blank");
  try {
    const r = await api("/api/demo", {method: "POST"});
    const b = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(b.error || "HTTP " + r.status);
    if (tab) tab.location = b.path; else location.assign(b.path);
  } catch (err) { if (tab) tab.close(); showError("The stage demo did not open: " + err.message); }
  showPop(null);
};
$("end").onclick = () => {
  if (!view.ended) { api("/api/stop", {method: "POST"}).then(() => { view.v = -1; if (wake) wake(); }); return; }
  api("/api/close", {method: "POST"}).finally(() => { closed = true; paintAll(); });
};

applyTheme();
setMode("idle");
if (talkMode === "live") startLive();
if (matchMedia("(hover: hover) and (pointer: fine)").matches) $("text").focus();
poll();
