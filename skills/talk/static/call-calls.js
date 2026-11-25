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
  floorNote = null;
  if (floorChannel) floorChannel.postMessage({call: CFG.call});
  api("/api/floor", {method: "POST", body: JSON.stringify(heard == null ? {} : {heard}), headers: {"Content-Type": "application/json"}})
    .then(r => r.ok ? r.json() : null).then(b => { if (b && epoch === floorEpoch) { floorN = b.floor_n; if (wake) wake(); } }).catch(() => {});
}
function topicOf(id) { const c = (view.calls || []).find(x => x.id === id); return c ? c.topic : ""; }
// Another call took the voice: this page paused, and says so in the state strip with a way back (floorNote), never
// in a toast over the board. The words name the call, not what it did: the page cannot tell playing from talking.
let floorNote = null;       // {id, topic}: why this call is paused, until the voice is taken back here or the note is dismissed
function floorWords(note) { return "Paused: " + (note.topic ? "“" + note.topic + "”" : "another call") + " took the voice."; }
function yieldFloor(id) {
  const busyHere = !audio.paused || !!recorder || listening();
  if (!audio.paused) audio.pause();
  if (recorder) { stopRecording(); setMode("idle"); }
  if (live) parkLive("floor");
  if (busyHere) {
    floorNote = {id, topic: topicOf(id)};
    // The collapsed rail has no strip to show it in: the toast says it there.
    if (rail) showError(floorWords(floorNote));
    paintAll();
  }
}
// Resume here, on the strip: this call takes the voice back and plays on from where it stopped. A play the reader
// starts, so it goes through readerPlays() and leaves following as it is.
function resumeHere() {
  floorNote = null;
  if (current && audio.paused) { readerPlays(current); takeVoice(); audio.play().catch(playFailed); }
  paintAll();
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

// ---- the state of a call, in words ---------------------------------------------
// One vocabulary for every call: this page's own call (hereInfo) and the others (callInfo, from view.calls). A state has a
// key (its glyph and colour), a word, and a rank: the lower, the more it needs the user. home.html (the All calls page)
// says the same words; test_call_calls.py holds the two together. Colour is never the only carrier: the glyph and the word go with it.
const CALL_NEED = ["stalled", "new", "answering", "playing", "talking", "waiting", "ended"];
const NEEDS_YOU = ["stalled", "new"];
const stateKind = key => ({key, rank: CALL_NEED.indexOf(key)});
// An other call, from the server's summary of it: {unheard, ended, stalled, working, floor, last_at}.
function callInfo(c) {
  if (c.unheard) return {...stateKind("new"), word: c.unheard === 1 ? "New answer" : c.unheard + " new answers"};
  if (c.ended) return {...stateKind("ended"), word: "Ended"};
  if (c.stalled) return {...stateKind("stalled"), word: "Stalled"};
  if (c.working) return {...stateKind("answering"), word: "Answering"};
  if (c.floor) return {...stateKind("talking"), word: "Talking now"};
  return {...stateKind("waiting"), word: "Waiting for you"};
}
function callState(c) { return callInfo(c).word; }
// This call, from the page's own state (the server's list leaves it out).
function hereInfo() {
  if (view.ended) return {...stateKind("ended"), word: "Ended"};
  if (view.stalled) return {...stateKind("stalled"), word: "Stalled"};
  if (recorder || (live && live.speech)) return {...stateKind("talking"), word: "Listening"};
  if (busy || view.working || waitActive()) return {...stateKind("answering"), word: "Answering"};
  if (current && !audio.paused) return {...stateKind("playing"), word: "Playing"};
  return {...stateKind("waiting"), word: "Waiting for you"};
}
// The other calls that need the user, the one that needs them most first (then the one that has waited longest).
function callsNeedingYou() {
  return (view.calls || []).map(c => ({c, info: callInfo(c)})).filter(x => NEEDS_YOU.includes(x.info.key))
    .sort((a, b) => a.info.rank - b.info.rank || (a.c.last_at || 0) - (b.c.last_at || 0) || (a.c.started || 0) - (b.c.started || 0));
}
function nextWaiting() { const list = callsNeedingYou(); return list.length ? list[0].c : null; }
function openNextWaiting() { const c = nextWaiting(); if (c) location.href = "/c/" + encodeURIComponent(c.id); }
// How long ago, in the fewest characters: now, 5m, 2h, 3d.
function ageText(seconds) {
  const s = Math.max(0, seconds || 0);
  return s < 45 ? "now" : s < 3600 ? Math.max(1, Math.round(s / 60)) + "m" : s < 86400 ? Math.floor(s / 3600) + "h" : Math.floor(s / 86400) + "d";
}
// The answers of this call that arrived while the user was not looking and have not been played.
function unheardHere() { return view.entries.filter(e => e.who === "claude" && e.id > Math.max(view.heard_upto ?? -1, shownUpto)); }
let shownUpto = -1;         // the newest answer that was in the list while this tab was in sight: it was not missed
function noteShown() {
  if (document.visibilityState !== "visible") return;
  for (const e of view.entries) if (e.who === "claude" && e.id > shownUpto) shownUpto = e.id;
}

// ---- the Calls popover: every call with its state, the one that needs you first --------------
const GLYPH_ATTR = 'viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const STATE_GLYPHS = {
  stalled: '<path d="M8 2.2 14.5 13.5h-13z"/><path d="M8 6.4v3.3M8 11.7v.1"/>',
  new: '<circle cx="8" cy="8" r="3.4" fill="currentColor" stroke="none"/>',
  answering: '<path d="M8 2a6 6 0 1 0 6 6"/>',
  playing: '<path d="M3.5 6v4M8 3v10M12.5 6v4"/>',
  talking: '<path d="M3.5 6v4M8 3v10M12.5 6v4"/>',
  paused: '<path d="M5.5 3.5v9M10.5 3.5v9"/>',
  waiting: '<path d="M2.5 3.5h11v7H7.6L4.5 13v-2.5h-2z"/>',
  ended: '<circle cx="8" cy="8" r="6"/><path d="M5.3 8.2l2 2 3.4-4"/>',
};
const glyphOf = key => `<svg ${GLYPH_ATTR}>${STATE_GLYPHS[key] || STATE_GLYPHS.waiting}</svg>`;
function callRow(c, info, here) {
  const a = document.createElement(here ? "div" : "a");
  if (!here) a.href = "/c/" + encodeURIComponent(c.id); else a.setAttribute("aria-current", "true");
  a.className = "callrow" + (here ? " here" : "") + (NEEDS_YOU.includes(info.key) ? " needs" : ""); a.dataset.state = info.key;
  const g = document.createElement("span"); g.className = "cg"; g.innerHTML = glyphOf(info.key);
  const m = document.createElement("span"); m.className = "cm";
  const t = document.createElement("span"); t.className = "ct"; t.textContent = c.topic;
  const s = document.createElement("span"); s.className = "cs"; s.textContent = (here ? "Here · " : "") + info.word;
  m.append(t, s);
  const age = document.createElement("span"); age.className = "ca"; age.textContent = here ? "" : ageText(serverNow() - (c.last_at || c.started || 0));
  a.title = c.topic + " · " + (here ? "this call · " : "") + info.word; a.append(g, m, age);
  return a;
}
function paintCalls() {
  const list = view.calls || [], nav = $("calls"), here = hereInfo();
  const rows = list.map(c => ({c, info: callInfo(c)})).sort((a, b) => a.info.rank - b.info.rank || (a.c.last_at || 0) - (b.c.last_at || 0));
  const sig = JSON.stringify([CFG.topic, here.key, here.word, rows.map(x => [x.c.id, x.c.topic, x.info.key, x.info.word, ageText(serverNow() - (x.c.last_at || x.c.started || 0))]), !!nextWaiting()]);
  if (nav.dataset.sig === sig) return;
  nav.dataset.sig = sig;
  const out = [];
  if (list.length) out.push(callRow({id: CFG.call, topic: CFG.topic}, here, true));
  for (const x of rows) out.push(callRow(x.c, x.info, false));
  nav.replaceChildren(...out);
  // The foot: the call that needs you most (hidden while none does), and the page of every call.
  const next = nextWaiting(), foot = $("nextwait");
  foot.replaceChildren();
  const all = document.createElement("a"); all.href = "/"; all.className = "btn callsall"; all.textContent = "All calls";
  if (next) {
    const b = document.createElement("button"); b.type = "button"; b.className = "btn callsnext"; b.id = "nextbtn"; b.onclick = openNextWaiting;
    b.title = "Open “" + next.topic + "”";
    b.innerHTML = '<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8h10M9 4l4 4-4 4"/></svg>';
    const w = document.createElement("span"); w.textContent = "Next waiting"; b.append(w); foot.append(b);
  }
  foot.append(all);
}
// Ages count up: the open popover repaints once a half minute, and only while it is open.
let callsClock = 0;
function paintCallsClock() {
  const open = !$("pCalls").hidden;
  if (open && !callsClock) callsClock = setInterval(() => { paintCalls(); paintCallsButton(); }, 30000);
  else if (!open && callsClock) { clearInterval(callsClock); callsClock = 0; }
}

// ---- the tab: title and icon carry the call's state ------------------------------------------
// Another tab shows what this one is doing: the state word first (a tab strip cuts the end), the count of answers
// missed in front of the topic. Driven by the poll, so a tab out of sight keeps it current; no clock, since a hidden tab's timers slow down.
function tabState() {
  const here = hereInfo(), missed = unheardHere().length;
  if (here.key === "ended" || here.key === "stalled" || here.key === "talking" || here.key === "answering" || here.key === "playing") {
    return {key: here.key, word: here.key === "talking" ? "Listening" : here.key === "stalled" ? "Stalled" : here.word, count: 0};
  }
  if (missed) return {key: "new", word: "New", count: missed};
  return {key: "idle", word: "", count: 0};
}
function tabTitle(t, topic) { return t.key === "idle" ? "Talk · " + topic : (t.count ? "(" + t.count + ") " : "") + t.word + " · " + topic; }
// The icon is a 32 px disc in the state's colour with its glyph, drawn as SVG (nothing to fetch, nothing to measure).
const FAV = {
  idle: ["#1967D2", '<circle cx="16" cy="16" r="5.2" fill="#fff"/>'],
  answering: ["#1967D2", '<path d="M16 7a9 9 0 1 0 9 9" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/>'],
  playing: ["#188038", '<path d="M10 13v6M16 9v14M22 13v6" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round"/>'],
  talking: ["#D93025", '<rect x="12.5" y="8" width="7" height="11" rx="3.5" fill="#fff"/><path d="M9.5 16a6.5 6.5 0 0 0 13 0M16 22.5v2.5" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>'],
  stalled: ["#F9AB00", '<path d="M16 8v10M16 22.6v.1" fill="none" stroke="#202124" stroke-width="3.6" stroke-linecap="round"/>'],
  ended: ["#80868B", '<path d="M10 16.5l4 4 8-9" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/>'],
};
function tabIcon(t) {
  const [bg, glyph] = t.key === "new"
    ? ["#1967D2", `<text x="16" y="22.5" font-family="Arial,sans-serif" font-size="19" font-weight="700" text-anchor="middle" fill="#fff">${t.count > 9 ? "9+" : t.count}</text>`]
    : FAV[t.key] || FAV.idle;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="15" fill="${bg}"/>${glyph}</svg>`;
  return "data:image/svg+xml," + encodeURIComponent(svg);
}
let tabSig = "";
function paintTab() {
  const t = tabState(), sig = t.key + "|" + t.count;
  if (sig === tabSig) return;
  tabSig = sig;
  document.title = tabTitle(t, CFG.topic);
  const link = $("favicon");
  if (link) { link.type = "image/svg+xml"; link.href = tabIcon(t); }
}

// ---- the hooks this file owns (R) -----------------------------------------------
// The Calls button and its count, painted from paintPill(): the calm layers icon while no other call needs you, else the glyph of the
// state that needs you most with how many calls do (amber when one is stalled). The words go in the name and the tooltip.
function paintCallsButton() {
  const calls = view.calls || [], need = callsNeedingYou(), btn = $("callsbtn");
  btn.hidden = !calls.length;
  $("callsdot").hidden = $("raildot").hidden = !need.length;
  $("callsdot").textContent = need.length ? String(need.length) : "";
  const top = need.length ? need[0].info.key : "";
  btn.dataset.need = top;
  const words = need.map(x => x.info.word + " in “" + x.c.topic + "”").join("; ");
  const label = need.length ? "Calls: " + need.length + (need.length === 1 ? " needs" : " need") + " you. " + words : "Calls";
  if (btn.getAttribute("aria-label") !== label) { btn.setAttribute("aria-label", label); btn.dataset.tip = need.length ? need.length + (need.length === 1 ? " call needs" : " calls need") + " you" : "Calls"; }
  const glyph = $("callsglyph");
  if (glyph.dataset.key !== top) { glyph.dataset.key = top; glyph.innerHTML = top ? glyphOf(top) : STACK_ICON; }
  paintCallsClock();
  // paintPill runs on every tick of the audio: the strip, the popover's rows and the tab follow what the page does at once
  // (a board pinned from the stage, a play, a pause) with nothing to repaint while the words are the same.
  paintCalls(); paintTab(); paintStateStrip();
}
const STACK_ICON = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/></svg>';
registerPop("callsbtn", "pCalls");
$("callsclose").onclick = ev => { ev.stopPropagation(); showPop(null); };
// A new view arrived: `before` is the one it replaces. The tab's title and icon, and a word to the live region when another call
// has a new answer. The floor note goes when the voice is back here.
function callsOnView(before) {
  if (floorNote && view.floor_call === CFG.call) floorNote = null;
  noteShown(); paintTab();
  const was = new Map((before.calls || []).map(c => [c.id, c.unheard || 0]));
  for (const c of view.calls || []) {
    if (was.has(c.id) && c.unheard > was.get(c.id)) announce("New answer in “" + c.topic + "”.");
  }
}
audio.addEventListener("play", () => { if (floorNote) { floorNote = null; paintAll(); } });
document.addEventListener("visibilitychange", () => { noteShown(); paintTab(); });
