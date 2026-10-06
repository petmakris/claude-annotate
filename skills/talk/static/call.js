// The call page: the stage fills the window, and Claude's last answer floats over its foot as
// subtitles, above a pill where typing and talking sit side by side; a gear holds the settings. talk.py serves it with window.CFG filled in for one call.
const CFG = window.CFG;
const $ = id => document.getElementById(id);
const SPEEDS = [0.75, 0.85, 1, 1.25, 1.5];
const store = {get(k, d){ try { const v = localStorage.getItem("talk." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
               set(k, v){ try { localStorage.setItem("talk." + k, JSON.stringify(v)); } catch {} }};
const api = (path, opts = {}) => fetch(path, {...opts, headers: {"X-Talk-Token": CFG.token, ...(opts.headers || {})}});
const fmt = s => { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const reduced = matchMedia("(prefers-reduced-motion: reduce)");

$("topic").textContent = CFG.topic; $("topic").title = CFG.topic; document.title = "Talk · " + CFG.topic;
// Which engine reads the answers aloud, always in view: Azure is fast and billed, VoiceStudio is local and slow.
if (CFG.engine) {
  const ava = /^[a-z]{2}-[A-Z]{2}-([A-Z][a-z]+)/.exec(CFG.voice || "");
  $("engine").textContent = CFG.engine + (CFG.engine === "Azure" && ava ? " · " + ava[1] : "");
  $("engine").title = CFG.engine === "Azure" ? "Speech by Azure, voice " + CFG.voice
    : "Speech by VoiceStudio on this Mac, voice profile " + CFG.voice;
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
  $("stage").addEventListener("load", () => { if ($("stage").getAttribute("src")) stageReady(); });
  $("reloadstage").onclick = loadStage;
  loadStage();
} else { $("stagewrap").remove(); $("nostage").hidden = false; }

// ---- talk and stage talk to each other -----------------------------------
// The protocol, also described at the top of stage.js. Talk to stage, posted to the stage's origin:
//   {type:'stage:front', view, manual}  bring a board to the front; manual: a chip was pressed
//   {type:'stage:frame', view, n, animate}  show frame n of a scene, animated when it is the next one
//   {type:'stage:state', front, frames, keys}  after a jump: the board in front, every scene's frame, the key point lit
//   {type:'stage:answer', n}            answer n started playing
//   {type:'stage:key', view, index}     key point number index (from 1) was just said: light it up
//   {type:'stage:theme', theme}         'light' or 'dark': the theme chosen here
//   {type:'stage:follow', on}           the gear's switch turned following on or off
// Stage to talk: {type:'stage:ready'}, {type:'stage:views', list:[{name, title, kind, answer}]} on every
// change, {type:'stage:changed', name, title, isNew}, and {type:'stage:follow', on} when following
// changes inside the stage (a tab tap turns it off, a new answer on), {type:'stage:key', key} for Space, ← or →
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
    toStage({type: "stage:follow", on: follow});
    for (const msg of stageOutbox.splice(0)) if (msg.type !== "stage:theme" && msg.type !== "stage:follow") toStage(msg);
    resync();
  }
  else if (m.type === "stage:follow") { follow = !!m.on; paintSettings(); if (follow) resync(); }
  else if (m.type === "stage:views") { stageViews = new Set((m.list || []).map(v => String(v.name))); paintMissing(); }
  else if (m.type === "stage:missing") paintMissing(String(m.view));
  else if (m.type === "stage:key" && MEDIA_KEYS.has(m.key)) mediaKey(m.key);
});

let stageViews = null;
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

// ---- popovers: one open at a time ---------------------------------------------
const POPS = {hist: "pHist", callsbtn: "pCalls", gear: "pGear"};
let openPop = null;
function showPop(pop) {
  openPop = pop && openPop !== pop ? pop : null;
  for (const [btn, id] of Object.entries(POPS)) {
    $(id).hidden = id !== openPop;
    $(btn).setAttribute("aria-expanded", String(id === openPop));
  }
  if (openPop === "pHist") $("convo").scrollTop = $("convo").scrollHeight;
}
for (const [btn, id] of Object.entries(POPS)) $(btn).onclick = ev => { ev.stopPropagation(); showPop(id); };
$("histx").onclick = () => showPop(null);
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && openPop) showPop(null); });
// A click anywhere else closes the open layer: the buttons that open layers stop their own click.
document.addEventListener("click", ev => {
  if (openPop && !ev.target.closest(".pop, .sheet, .toast")) showPop(null);
});
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
let subsOff = store.get("subsOff", false);  // the subtitles were hidden: the pill's captions button brings them back

// ---- the conversation --------------------------------------------------
// Keyed: each entry keeps its element until what it shows changes, so a new entry leaves the others
// (and a text selection in them) alone.
const nodes = new Map();    // entry id -> {el, sig}
let rendered = false;
const sigOf = e => `${e.who}|${e.text.length}|${e.speech}|${e.words?.length || 0}|${e.speech_error || ""}|${e.n || 0}`;

function buildEntry(e) {
  let el;
  if (e.who === "you" || e.who === "claude") {
    el = document.createElement("div"); el.className = "turn " + e.who;
    const who = document.createElement("div"); who.className = "who"; who.textContent = e.who === "you" ? "You" : "Claude";
    if (e.who === "claude") { const s = document.createElement("small"); s.textContent = "answer " + e.n; who.append(s); }
    if (e.typed) { const s = document.createElement("small"); s.textContent = "typed"; who.append(s); }
    const text = document.createElement("div"); text.className = "text";
    text.textContent = e.text;
    el.dataset.id = e.id;
    el.append(who, text);
    if (e.who === "claude") {
      if (e.speech === "ready") {
        const b = document.createElement("button"); b.className = "btn play"; b.type = "button";
        b.onclick = () => (current && current.id === e.id && !audio.paused) ? audio.pause() : load(view.entries.find(x => x.id === e.id) || e, true);
        el.append(b);
      } else {
        const s = document.createElement("div"); s.className = "speech" + (e.speech === "failed" ? " bad" : "");
        s.textContent = e.speech === "failed" ? "Not read aloud: " + (e.speech_error || "speech failed") : "Preparing the audio…"; el.append(s);
      }
      paintTurn(el, e.id);
    }
  } else if (e.who === "status") {
    el = document.createElement("div"); el.className = "line status"; el.textContent = "Claude: " + e.text;
  } else if (e.who === "board") {
    // A button: it brings its board to the front of the stage, and the sheet steps aside to show it.
    el = document.createElement("button"); el.type = "button"; el.className = "chip board"; el.dataset.view = e.view || "";
    el.innerHTML = kindIcon(e.kind);
    const t = document.createElement("span"); t.textContent = e.text; el.append(t);
    el.setAttribute("aria-label", e.kind === "points" ? e.text : "On the stage: " + e.text);
    if (!CFG.stageUrl || !e.view) { el.disabled = true; el.title = "The stage is not available"; }
    else el.onclick = () => { toStage({type: "stage:front", view: e.view, manual: true}); showPop(null); };
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
  if (atEnd) box.scrollTop = box.scrollHeight;
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

// ---- the subtitles: the answer in the player, else the last one ---------------
const capEl = $("cap");
let capFor = null, capSig = "", capSpans = [];
function lastAnswer() {
  for (let i = view.entries.length - 1; i >= 0; i--) if (view.entries[i].who === "claude") return view.entries[i];
  return null;
}
function shownAnswer() { return current ? (view.entries.find(e => e.id === current.id) || current) : lastAnswer(); }
// Every timed word is a span: lit as it is said, and a tap plays from there.
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
function paintSubs() {
  const you = view.entries.findLast(e => e.who === "you");
  $("askedtext").textContent = you ? you.text : "";
  const e = shownAnswer(), sig = e ? e.id + "|" + sigOf(e) : (view.ended ? "ended" : "none");
  if (sig !== capSig) {
    // The answer gets its word timings once its audio is made: it is rebuilt in place, keeping
    // its marks and its scroll, and the word being said is lit again at once.
    const same = !!e && e.id === capFor, top = capEl.scrollTop;
    capSig = sig; lastWord = null; lastK = -2;
    if (e) { if (!same) capEl.className = "cap"; capEl.replaceChildren(...wordSpans(e)); }
    else { capEl.className = "cap"; capEl.textContent = ""; }
    capSpans = [...capEl.querySelectorAll(".w")]; capFor = e ? e.id : null;
    capEl.scrollTo({top: same ? top : 0, behavior: "instant"});
    if (same) highlight();
  }
  let note = "", bad = false;
  if (e && e.speech === "failed") { note = "Not read aloud: " + (e.speech_error || "speech failed"); bad = true; }
  $("capnote").textContent = note; $("capnote").classList.toggle("bad", bad);
  // Hidden subtitles hide the answer and keep the status: what Claude is doing still shows.
  const s = statusText(), covered = !!recorder || busy || (!!view.working && !view.ended), off = subsOff;
  $("asked").hidden = !you || !!recorder || off;
  capEl.hidden = covered || !e || off; $("capnote").hidden = covered || !note || off;
  paintPrep(covered || off ? null : e);
  $("wave").hidden = !recorder;
  $("status").hidden = !s;
  if (s) { $("status").textContent = s.text; $("status").className = "status" + (s.shimmer ? " shimmer" : "") + (s.warn ? " warn" : ""); }
  $("seek").hidden = covered || !current || off;
  const answer = !($("asked").hidden && capEl.hidden && $("capnote").hidden && $("prep").hidden && $("seek").hidden);
  $("subs").hidden = !answer && !s;
  $("subsx").hidden = !answer;
  $("subsbtn").hidden = !off || !!recorder;
}
function setSubs(on) { subsOff = !on; store.set("subsOff", subsOff); paintSubs(); if (on && current) { lastK = -2; highlight(); } }
$("subsx").onclick = () => setSubs(false);
$("subsbtn").onclick = () => setSubs(true);
// The line under the stage while there is no answer to read: the first that applies.
function statusText() {
  if (recorder) return null;
  if (busy) return {text: "Turning your words into text…", shimmer: true};
  if (view.ended) return {text: closed ? "Closed. You can close this tab." : "The call has ended: " + view.ended + ". Answers can still be replayed."};
  if (view.stalled) return {text: "Claude has not picked this up yet. Check the terminal: the session may be waiting for a permission.", warn: true};
  if (view.working) {
    const run = view.activity.filter(a => a.state === "running").pop();
    return {text: run ? run.label + " · " + Math.round(run.seconds) + "s" : "Claude is working…", shimmer: true};
  }
  return null;
}
function appState() {
  if (recorder) return "listening";
  if (busy || (view.working && !view.ended)) return "working";
  if (current && !audio.paused) return "speaking";
  return "idle";
}
function paintPill() {
  const rec = !!recorder, ended = !!view.ended, shown = shownAnswer();
  $("talk").hidden = ended; $("talk").disabled = busy; $("talk").classList.toggle("busy", busy);
  $("talk").setAttribute("aria-label", rec ? "Send" : "Talk"); $("talk").dataset.tip = rec ? "Send" : "Talk";
  $("cancel").hidden = !rec; $("send").hidden = !rec;
  $("hist").hidden = rec; $("compose").hidden = rec || ended; $("sendtext").hidden = rec || ended;
  $("back").hidden = rec || !current;
  $("playpause").hidden = rec || !shown || shown.speech !== "ready";
  const label = !audio.paused ? "Pause" : (current && (audio.ended || audio.currentTime >= (audio.duration || 1)) ? "Play again" : "Play");
  $("playpause").setAttribute("aria-label", label); $("playpause").dataset.tip = label + " · Space";
  $("playpause").classList.toggle("playing", !audio.paused);
  const calls = view.calls || [];
  $("callsbtn").hidden = rec || !calls.length; $("sep").hidden = $("callsbtn").hidden;
  $("callsdot").hidden = !calls.some(c => c.unheard);
  const d = audio.duration || 0;
  $("seek").max = d; $("seek").value = audio.currentTime || 0;
  $("seek").style.setProperty("--p", (d ? 100 * audio.currentTime / d : 0) + "%");
  $("seek").title = fmt(audio.currentTime) + " / " + fmt(d);
  $("live").classList.toggle("off", ended);
}
function paintSettings() {
  for (const b of $("speeds").children) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
  for (const b of $("lang").children) b.setAttribute("aria-pressed", String(b.dataset.lang === language));
  $("autoplay").setAttribute("aria-pressed", String(autoplay));
  $("follow").setAttribute("aria-pressed", String(follow)); $("follow").disabled = !CFG.stageUrl;
  $("endlbl").textContent = view.ended ? "Close" : "End call"; $("end").disabled = closed;
}
function paintAll() {
  paintSubs(); paintPill(); paintSettings();
  $("app").dataset.state = appState(); $("app").toggleAttribute("data-ended", !!view.ended);
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
function takeFloor(heard) {
  const epoch = ++floorEpoch;
  if (floorChannel) floorChannel.postMessage({call: CFG.call});
  api("/api/floor", {method: "POST", body: JSON.stringify(heard == null ? {} : {heard}), headers: {"Content-Type": "application/json"}})
    .then(r => r.ok ? r.json() : null).then(b => { if (b && epoch === floorEpoch) { floorN = b.floor_n; if (wake) wake(); } }).catch(() => {});
}
function topicOf(id) { const c = (view.calls || []).find(x => x.id === id); return c ? c.topic : ""; }
function yieldFloor(id) {
  const busyHere = !audio.paused || !!recorder;
  if (!audio.paused) audio.pause();
  if (recorder) { stopRecording(); setMode("idle"); }
  if (busyHere) { const t = topicOf(id); showError("Paused: you are talking in " + (t ? "“" + t + "”" : "another call") + "."); }
}
if (floorChannel) floorChannel.onmessage = ev => { const id = ev.data && ev.data.call; if (id && id !== CFG.call) yieldFloor(id); };
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
// audio is ready, a bar under the subtitles fills toward the server's estimate of how long it takes,
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
  // Only the call the user is talking in reads new answers aloud; another call's wait, marked new.
  const mine = !view.floor_call || view.floor_call === CFG.call;
  if (!current || audio.paused || audio.ended) load(last, autoplay && !recorder && mine);
}
// ---- the word being said ------------------------------------------------
function playFrom(e, t) {
  // Play the answer from time `t` seconds in.
  e = view.entries.find(x => x.id === e.id) || e;
  if (e.speech !== "ready") return;
  cueSync = true;
  load(e, false); audio.currentTime = t;
  audio.playbackRate = speed; audio.play().catch(() => {});
}
function wordAt(e, t) {
  // The last word that has started by time t, or -1.
  let lo = 0, hi = e.words.length - 1, k = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (e.words[m][2] <= t) { k = m; lo = m + 1; } else hi = m - 1; }
  return k;
}
// The word being said is lit, the words before it are full ink, and its line stays on the bottom
// row of the subtitles. A paused answer keeps its place; one played to its end reads in full.
let lastWord = null, lastK = -2;
function keepInView(el) {
  const want = Math.max(0, el.offsetTop + el.offsetHeight - capEl.clientHeight);
  if (Math.abs(capEl.scrollTop - want) > 2) capEl.scrollTo({top: want, behavior: reduced.matches ? "auto" : "smooth"});
  capEl.classList.toggle("scrolled", want > 0);
}
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
  const onCap = !!e && capFor === e.id;
  const reading = onCap && k >= 0;
  capEl.classList.toggle("reading", reading);
  if (!reading) k = -1;
  if (k === lastK) return;
  const was = lastK; lastK = k;
  for (let i = 0; i < capSpans.length; i++) capSpans[i].classList.toggle("said", i < k);
  if (lastWord) lastWord.classList.remove("now-word");
  lastWord = k >= 0 ? capSpans[k] || null : null;
  if (lastWord) { lastWord.classList.add("now-word"); keepInView(lastWord); }
  else if (was >= 0) { capEl.scrollTo({top: 0}); capEl.classList.remove("scrolled"); }
}

// ---- the board follows the voice ------------------------------------------
const LEAD_S = 0.12;
let cueSync = true, sent = null;
function stateAt(e, pos) {
  const cues = e.cues || [], st = {front: null, frames: {}, key: null};
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
    toStage({type: "stage:state", front: st.front, frames: st.frames, keys: st.key ? st.key.index : 0});
  } else {
    if (st.front && st.front !== sent.front) toStage({type: "stage:front", view: st.front, manual: false});
    for (const [view, n] of Object.entries(st.frames)) {
      if (sent.frames[view] !== n) toStage({type: "stage:frame", view, n, animate: n === sent.frames[view] + 1});
    }
    if (st.key && (!sent.key || st.key.at !== sent.key.at || st.key.index !== sent.key.index)) toStage({type: "stage:key", view: st.key.view, index: st.key.index});
  }
  cueSync = false;
  sent = {id: e.id, ...st};
}
function resync() { cueSync = true; highlight(); }
let failedShown = null;
function showFailedAnswer() {
  const e = lastAnswer();
  if (!e || e.speech !== "failed" || failedShown === e.id) return;
  failedShown = e.id; cueSync = true; syncStage(e, Infinity);
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
audio.addEventListener("ended", () => { if (current) syncStage(view.entries.find(x => x.id === current.id) || current, Infinity); });
audio.addEventListener("seeking", () => { cueSync = true; });
function skip(by) { audio.currentTime = Math.min(Math.max(0, audio.currentTime + by), audio.duration || 0); paintPill(); }
function togglePlay() {
  if (!current) { const e = lastAnswer(); if (e) load(e, true); return; }
  if (audio.paused) audio.play().catch(() => {}); else audio.pause();
}
$("playpause").onclick = togglePlay;
$("back").onclick = () => skip(-10);
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
  if (recorder || busy || openPop) return false;
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
    || (at.tagName === "BUTTON" && !!at.closest("#pill, #subs"));
  if (!free) return;
  if (ev.key === " " && ev.repeat) { ev.preventDefault(); return; }
  if (mediaKey(ev.key)) ev.preventDefault();
});
if ("mediaSession" in navigator) {
  const ms = navigator.mediaSession;
  ms.setActionHandler("play", () => audio.play()); ms.setActionHandler("pause", () => audio.pause());
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
    if (resp.ok) { $("text").value = ""; fitText(); view.v = -1; } else showError(body.error || "Sending failed: HTTP " + resp.status);
  } catch (err) { showError("Sending failed: " + err.message); }
  $("sendtext").disabled = !$("text").value.trim();
}
// The text field grows with what is typed, up to a few lines, and Send waits for something to send.
function fitText() {
  const t = $("text"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 120) + "px";
  $("sendtext").disabled = !t.value.trim();
}
$("text").addEventListener("input", fitText);
const narrow = matchMedia("(max-width: 700px)");
function placeholder() { $("text").placeholder = narrow.matches ? "Type or talk" : "Type to Claude, or press the mic to talk"; }
narrow.addEventListener("change", placeholder); placeholder();
// Typing is as direct as talking: a key pressed anywhere on the page goes to the text field.
document.addEventListener("keydown", ev => {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1 || openPop || recorder || view.ended) return;
  if (document.activeElement && document.activeElement !== document.body) return;
  $("text").focus();
});

$("talk").onclick = () => recorder ? sendRecording() : startRecording();
$("send").onclick = sendRecording;
$("cancel").onclick = () => { stopRecording(); setMode("idle"); };
$("sendtext").onclick = sendText;
$("text").addEventListener("keydown", ev => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); sendText(); } });
$("end").onclick = () => {
  if (!view.ended) { api("/api/stop", {method: "POST"}).then(() => { view.v = -1; if (wake) wake(); }); return; }
  api("/api/close", {method: "POST"}).finally(() => { closed = true; paintAll(); });
};

applyTheme();
setMode("idle");
if (matchMedia("(hover: hover) and (pointer: fine)").matches) $("text").focus();
poll();
