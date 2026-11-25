// Which voice reads the answers aloud, in the settings, in plain words: no machine, no profile, nothing an owner needs.
// Azure is quick to start and billed per character; the local engine is free and about as slow to make an answer as to say it.
function engineText() {
  if (CFG.engine === "Azure") {
    const ava = /^[a-z]{2}-[A-Z]{2}-([A-Z][a-z]+)/.exec(CFG.voice || "");
    return ((CFG.voices || []).length ? "" : (ava ? ava[1] : CFG.voice) + ", ") + "a cloud voice: quick to start, billed per character";
  }
  return "A voice made on this computer: free, a little slower to start";
}
if (CFG.engine) { $("engine").textContent = engineText(); $("engine").hidden = false; }
// ---- the voice: the engine's voices to pick from, the choice kept on this origin ------------------
// The server makes each answer's audio as the answer arrives, so the choice is sent to it: when the page
// opens and whenever it changes. Answers already made keep the voice they were made in. A voice's sample
// is a few words, made once by the server and kept.
const VOICES = CFG.voices || [];
let voice = CFG.voice;
const sample = new Audio();
function paintVoices() {
  for (const b of $("voices").querySelectorAll(".vpick")) b.setAttribute("aria-checked", String(b.dataset.voice === voice));
}
function chooseVoice(id, send = true) {
  voice = id; store.set("voice", id); paintVoices();
  if (send) api("/api/voice", {method: "POST", body: JSON.stringify({voice: id}), headers: {"Content-Type": "application/json"}})
    .then(r => { if (!r.ok) showError("The voice was not changed."); }).catch(() => showError("The voice was not changed."));
}
if (VOICES.length) {
  for (const v of VOICES) {
    const row = document.createElement("div"); row.className = "vrow";
    const pick = document.createElement("button"); pick.type = "button"; pick.className = "vpick"; pick.dataset.voice = v.id;
    pick.setAttribute("role", "radio"); pick.append(v.name);
    const note = document.createElement("small"); note.textContent = v.note; pick.append(note);
    pick.onclick = () => chooseVoice(v.id);
    const hear = document.createElement("button"); hear.type = "button"; hear.className = "ib";
    hear.setAttribute("aria-label", "Hear " + v.name); hear.title = "Hear " + v.name;
    hear.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z"/></svg>';
    hear.onclick = () => {
      sample.src = location.pathname.replace(/\/$/, "") + "/voice/" + encodeURIComponent(v.id);
      sample.play().catch(() => showError("The sample did not play."));
    };
    row.append(pick, hear); $("voices").append(row);
  }
  $("voices").hidden = false;
  const kept = store.get("voice", null);
  if (kept && kept !== voice && VOICES.some(v => v.id === kept)) chooseVoice(kept);
  paintVoices();
}

// ---- the theme: light, dark, or the system's ------------------------------
// <html> always carries data-theme; the head script set it before the first paint. Until the user picks one, the page follows the system.
const darkMq = matchMedia("(prefers-color-scheme: dark)");
let theme = ["light", "dark", "system"].includes(store.get("theme", "system")) ? store.get("theme", "system") : "system";
function applyTheme() {
  const t = theme === "dark" || (theme === "system" && darkMq.matches) ? "dark" : "light";
  document.documentElement.dataset.theme = t;
  toStage({type: "stage:theme", theme: t});
  for (const b of $("theme").children) b.setAttribute("aria-pressed", String(b.dataset.choice === theme));
}
for (const b of $("theme").children) b.onclick = () => { theme = b.dataset.choice; store.set("theme", theme); applyTheme(); };
darkMq.addEventListener("change", () => { if (theme === "system") applyTheme(); });

// ---- full screen: the whole page, stage and pill, for a TV or a call that needs the room ----
function paintFullscreen() {
  const on = !!document.fullscreenElement;
  $("fullscreen").setAttribute("aria-pressed", String(on));
  $("fullscreen").setAttribute("aria-label", on ? "Leave full screen" : "Full screen");
  $("fullscreen").dataset.tip = on ? "Leave full screen" : "Full screen";
}
// A browser that cannot take the page full screen (an iPhone, a frame without the permission) shows no button.
$("fullscreen").hidden = !document.fullscreenEnabled;
// Full screen on a big display with no screen size chosen yet is the TV's size too, for as long as it lasts: nobody at a
// TV goes looking for a setting. A size picked in the gear or named in the address (?screen=tv) always wins.
const TV_WIDTH = 1700;
let tvByFullscreen = false;
function setScreen(mode, keep = true) {
  screenMode = mode === "tv" ? "tv" : "desk"; if (keep) { store.set("screen", screenMode); tvByFullscreen = false; }
  toStage({type: "stage:zoom", zoom: screenMode === "tv" ? TV_ZOOM : 1}); paintAll();
}
$("fullscreen").onclick = () => {
  if (!document.fullscreenElement && screenMode === "desk" && innerWidth >= TV_WIDTH && store.get("screen", null) === null) { tvByFullscreen = true; setScreen("tv", false); }
  const go = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  go.catch(err => { showError("Full screen failed: " + err.message); if (tvByFullscreen) { tvByFullscreen = false; setScreen("desk", false); } });
};
const screenParam = new URLSearchParams(location.search).get("screen");
if (screenParam === "tv" || screenParam === "desk") { screenMode = screenParam; store.set("screen", screenMode); }
// Esc and the browser's own controls leave full screen too: the button follows whatever happened.
document.addEventListener("fullscreenchange", () => {
  paintFullscreen();
  if (!document.fullscreenElement && tvByFullscreen) { tvByFullscreen = false; setScreen("desk", false); }
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

function paintSettings() {
  for (const b of $("speeds").children) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
  for (const b of document.querySelectorAll("[data-speedchip]")) {
    b.textContent = speed + "×"; b.setAttribute("aria-label", "Voice speed " + speed + "×. Press for the next speed.");
  }
  for (const b of $("lang").children) b.setAttribute("aria-pressed", String(b.dataset.lang === language));
  $("autoplay").setAttribute("aria-pressed", String(autoplay));
  $("follow").setAttribute("aria-pressed", String(follow)); $("follow").disabled = !CFG.stageUrl;
  for (const b of $("screen").children) b.setAttribute("aria-pressed", String(b.dataset.choice === screenMode));
  $("endlbl").textContent = view.ended ? "Close" : "End call"; $("end").disabled = closed;
}
for (const s of SPEEDS) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.speed = s; b.textContent = s + "×";
  b.onclick = () => setSpeed(s);
  $("speeds").append(b);
}
$("autoplay").onclick = () => { autoplay = !autoplay; store.set("autoplay", autoplay); paintSettings(); };
// ---- the keys ----------------------------------------------------------------------
// Every shortcut of the page is in this list, once: the Keys sheet (#pKeys) and the hint under the field are built from it,
// and test_call_input.py presses each row. Letters belong to the message field (a key typed anywhere lands in it), so the
// shortcuts that are not Space, the arrows or ? are Alt chords, read from the physical key (ev.code: Option types a
// character on a Mac). Every key does what a visible button does.
const KEYS = [
  {group: "Listening", rows: [
    {id: "play", keys: ["Space"], what: "Play or pause the answer"},
    {id: "sentence", keys: ["←", "→"], what: "Back or forward one sentence"},
    {id: "speed", keys: ["Alt", "S"], what: "Next voice speed"}]},
  {group: "Moving around", rows: [
    {id: "message", keys: ["Alt", "M"], what: "Go to the message field"},
    {id: "player", keys: ["Alt", "P"], what: "Go to the player"},
    {id: "voice", keys: ["Alt", "V"], what: "Follow the voice again"},
    {id: "keys", keys: ["?"], what: "Show this list"},
    {id: "close", keys: ["Esc"], what: "Close the open window"}]},
  {group: "Talking", rows: [
    {id: "send", keys: ["Enter"], what: "Send the message"},
    {id: "newline", keys: ["Shift", "Enter"], what: "New line in the message"},
    {id: "talk", keys: ["Alt", "T"], what: "Talk, or Done while recording"}]},
];
const ALT_KEYS = {KeyS: "speed", KeyM: "message", KeyP: "player", KeyV: "voice", KeyT: "talk"};
function buildKeys() {
  const pop = $("pKeys"), make = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
  const head = make("div", "khead"), close = make("button", "ib kclose"); close.type = "button"; close.setAttribute("aria-label", "Close the shortcuts");
  close.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>';
  close.onclick = () => showPop(null);
  head.append(make("h3", "", "Keyboard shortcuts"), close);
  const body = make("div", "kbody");
  for (const g of KEYS) {
    const sec = make("section", "kgroup"); sec.append(make("h4", "", g.group));
    for (const r of g.rows) {
      const row = make("div", "krow"), keys = make("span", "kk");
      r.keys.forEach((k, i) => { if (i) keys.append(" "); keys.append(make("kbd", "", k)); });
      row.dataset.key = r.id; row.append(keys, make("span", "kw", r.what)); sec.append(row);
    }
    body.append(sec);
  }
  pop.replaceChildren(head, body, make("p", "knote", "Every key has a button. Letters go to the message field, so the shortcuts use Alt."));
}
buildKeys();
popButton("keysbtn", "pKeys"); popButton("keysrow", "pKeys");
// Nothing is being typed: the body, an empty message field or a button of the panel has the focus.
function keysFree() {
  const at = document.activeElement;
  return !at || at === document.body || (at === $("text") && !$("text").value) || (at.tagName === "BUTTON" && !!at.closest("#panel"))
    || (openPop === "pKeys" && $("pKeys").contains(at));
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
  if (!keysFree()) return;
  if (ev.key === " " && ev.repeat) { ev.preventDefault(); return; }
  if (mediaKey(ev.key)) ev.preventDefault();
});
// The Alt chords and ?: before the typing handler below, which skips a key already used.
document.addEventListener("keydown", ev => {
  if (ev.ctrlKey || ev.metaKey) return;
  if (ev.altKey && !ev.shiftKey && ALT_KEYS[ev.code]) { if (runShortcut(ALT_KEYS[ev.code])) ev.preventDefault(); return; }
  if (ev.key === "?" && !ev.altKey && keysFree()) { ev.preventDefault(); showPop("pKeys"); }
});
function runShortcut(id) {
  if (id === "speed") { cycleSpeed(); return true; }
  if (id === "message") { if (rail) setRail(false); $("text").focus(); return true; }
  if (id === "player") { const b = $(rail ? "railpp" : "playpause"); if (!b || b.closest("[hidden]")) return false; b.focus(); return true; }
  if (id === "voice") { if (!CFG.stageUrl) return false; followAgain(); return true; }
  if (id === "talk") { talkPress(); return true; }
  return false;
}
// The skip links, the first stops of the page: past the stage and every answer, to the message or to the player.
for (const [id, to] of [["skipmsg", "message"], ["skipplay", "player"]]) {
  $(id).onclick = ev => { ev.preventDefault(); runShortcut(to); };
}
// Back is one sentence, as the left arrow is, never a fixed ten seconds that restarts a short answer; the position slider's
// arrows are the same sentence steps, Page Up and Page Down ten seconds. Guarded: the player's markup is another batch's.
for (const id of ["back", "railback"]) { const b = $(id); if (b) b.onclick = () => { if (current) jump(-1); }; }
if ($("seek")) $("seek").addEventListener("keydown", ev => {
  if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") { ev.preventDefault(); if (current) jump(ev.key === "ArrowLeft" ? -1 : 1); }
  else if (ev.key === "PageUp" || ev.key === "PageDown") { ev.preventDefault(); skip(ev.key === "PageUp" ? 10 : -10); }
});
if ("mediaSession" in navigator) {
  const ms = navigator.mediaSession;
  ms.setActionHandler("play", () => { readerPlays(current); audio.play(); }); ms.setActionHandler("pause", () => audio.pause());
  ms.setActionHandler("seekbackward", d => skip(-(d.seekOffset || 10))); ms.setActionHandler("seekforward", d => skip(d.seekOffset || 10));
}

// ---- talking -----------------------------------------------------------
const LANG_NAMES = {auto: "Detect", en: "English", el: "Ελληνικά"};
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

// A recording comes back as words in the text field, to be checked and changed before Send; nothing
// reaches Claude until then. While the server restarts (503, or no answer at all) the recording is sent
// again until the next server takes it, for up to three minutes. One still not taken is kept for Send again.
async function sendWav(wav) {
  unsent = null;
  setMode("busy");
  const until = Date.now() + 180000;
  for (let wait = 1000; ; wait = Math.min(wait * 2, 8000)) {
    let resp = null, failed = "";
    try { resp = await api("/api/listen?draft=1&lang=" + language, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}}); }
    catch (err) { failed = err.message; }
    if (resp && resp.status !== 503) {
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) { if (![410, 413].includes(resp.status)) unsent = wav; showError(body.error || "Sending failed: HTTP " + resp.status); }
      else if (!body.text) showError("Nothing was heard. Try again, a little closer to the microphone.");
      else writeOut(body.text);
      break;
    }
    if (Date.now() > until) { unsent = wav; showError("Sending failed: " + (failed || "the talk server is restarting")); break; }
    errText = "Reconnecting… your recording is kept and will be written out."; paintToast();
    await new Promise(ok => setTimeout(ok, wait));
  }
  if (errText.startsWith("Reconnecting…")) showError("");
  setMode("idle");
}

// Typing is as direct as talking: a key pressed anywhere on the page goes to the text field.
document.addEventListener("keydown", ev => {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1 || openPop || recorder || view.ended) return;
  if (document.activeElement && document.activeElement !== document.body) return;
  $("text").focus();
});

for (const b of $("screen").children) b.onclick = () => setScreen(b.dataset.choice);
function setTalkMode(mode) {
  talkMode = mode; store.set("talkMode", mode);
  if (mode === "live") { if (recorder) sendRecording(); startLive(); }   // an open recording goes first, once
  else stopLive();
  paintAll();
}

// ---- how you talk: Type, Talk or Live, a switch on the foot --------------------------
// inputMode is what the switch shows; talkMode (shared with the live code) is its two-way reduction: Live is "live", Type and
// Talk are "manual" (nothing listens between turns). Type puts the mic away and the cursor in the field. A switch kept by an
// earlier version is read from its talkMode.
const MODES = [
  {id: "type", label: "Type", icon: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>'},
  {id: "talk", label: "Talk", icon: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5"/>'},
  {id: "live", label: "Live", icon: '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>'},
];
let inputMode = (m => MODES.some(x => x.id === m) ? m : talkMode === "live" ? "live" : "talk")(store.get("inputMode", null));
talkMode = inputMode === "live" ? "live" : "manual";
function setInputMode(mode) {
  if (!MODES.some(x => x.id === mode) || recorder || (busy && talkMode !== "live")) return false;
  inputMode = mode; store.set("inputMode", mode);
  setTalkMode(mode === "live" ? "live" : "manual");
  if (mode === "type") $("text").focus();
  return true;
}
const BARGE_SAYS = {talk: "talking", keyword: "“wait”"}, PAUSES = [800, 1200, 2000];
function buildModes() {
  const sw = $("modesw");
  for (const m of MODES) {
    const b = document.createElement("button"); b.type = "button"; b.dataset.mode = m.id; b.setAttribute("aria-pressed", "false");
    b.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + m.icon + "</svg>";
    const w = document.createElement("span"); w.textContent = m.label; b.append(w);
    b.onclick = () => setInputMode(m.id);
    sw.append(b);
  }
  // Live's two options, one tap each to the next value: they were two groups of the gear.
  const opts = document.createElement("div"); opts.className = "livepills"; opts.id = "livepills"; opts.hidden = true;
  const barge_ = document.createElement("button"), pause_ = document.createElement("button");
  barge_.id = "bargepill"; pause_.id = "pausepill";
  for (const b of [barge_, pause_]) { b.type = "button"; b.className = "pillbtn"; }
  barge_.onclick = () => { barge = barge === "talk" ? "keyword" : "talk"; store.set("barge", barge); paintInputMode(); };
  pause_.onclick = () => { endPause = PAUSES[(PAUSES.indexOf(endPause) + 1) % PAUSES.length]; store.set("endPause", endPause); paintInputMode(); };
  opts.append(barge_, pause_); $("modebar").append(opts);
}
buildModes();
// Whose turn it is, in words: the Your turn pill. `key` styles it, `text` is what it says; null (no pill) once the call ended.
function yourTurnState() {
  if (view.ended) return null;
  if (recorder) return {key: "rec", text: "Recording"};
  if (busy && talkMode !== "live") return {key: "work", text: "Writing it out"};
  if (talkMode === "live") {
    if (!live) return {key: "off", text: "Live is off"};
    if (live.suspended) return {key: "warn", text: "Click to start listening"};
    if (live.parked) return {key: "off", text: "Live on another screen"};
    if (live.muted) return {key: "off", text: "Muted"};
    if (live.noSignal) return {key: "warn", text: "No sound heard"};
    if (live.speech) return {key: "live", text: "Hearing you"};
  }
  if ($("text").value.trim()) return {key: "typing", text: "Typing"};
  const st = appState();
  if (st === "working") return {key: "work", text: "Claude is working"};
  if (st === "speaking") return {key: "speak", text: "Claude is speaking"};
  return talkMode === "live" ? {key: "live", text: "Listening"} : {key: "turn", text: "Your turn"};
}
$("text").addEventListener("input", () => paintInputMode());
// The voice speed, one press to the next: the player's chip and Alt+S.
function cycleSpeed() { setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]); announce("Voice speed " + speed + "×"); }
for (const b of document.querySelectorAll("[data-speedchip]")) b.onclick = cycleSpeed;

// In live mode the mic button mutes and unmutes the open microphone (the stream, the floor and this page's claim stay); while
// Chrome holds the audio back it starts it, and the same press must not then mute. Leaving Live is the switch.
function liveButton() {
  if (live && (live.suspended || performance.now() - wokeAt < 1000)) { wakeLive(); return; }
  if (live && live.parked) { claimLive(); return; }
  if (live) setMuted(!live.muted); else startLive();
}
// What the mic button does: the page's one Talk press, for the button, the rail's and Alt+T.
function talkPress() {
  if (inputMode === "type" && !recorder) setInputMode("talk");
  if (busy && talkMode !== "live") return;
  if (talkMode === "live") liveButton(); else if (recorder) sendRecording(); else startRecording();
}
$("talk").onclick = $("railtalk").onclick = talkPress;
$("send").onclick = sendRecording;
$("cancel").onclick = () => { stopRecording(); setMode("idle"); };
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

// ---- the hooks this file owns (I) -----------------------------------------------
// The mic and the text field, painted from paintPill(): the talk buttons of the panel and the rail, Cancel and Done while
// recording, the text field, the Send button. Type puts the mic away; in Live the button mutes.
function paintMic() {
  const rec = !!recorder, ended = !!view.ended;
  const liveMode = talkMode === "live";
  const liveLabel = !live ? "Listen" : live.suspended ? "Start listening" : live.parked ? "Listen here" : live.muted ? "Unmute" : "Mute";
  const talkLabel = rec ? "Done" : liveMode ? liveLabel : "Talk";
  // The rail's mic is the panel's: the same label, the same look.
  for (const id of ["talk", "railtalk"]) {
    const b = $(id);
    b.hidden = ended || (inputMode === "type" && !rec); b.disabled = busy && !liveMode; b.classList.toggle("busy", busy && !liveMode);
    b.setAttribute("aria-label", talkLabel); b.dataset.tip = talkLabel + (id === "talk" ? " · Alt+T" : "");
    b.classList.toggle("live", liveMode); b.classList.toggle("muted", liveMode && !listening());
  }
  $("cancel").hidden = !rec; $("send").hidden = !rec;
  $("text").hidden = rec || ended; $("sendtext").hidden = rec || ended; $("pill").hidden = ended && !rec;
}
// The Type / Talk / Live switch (#modesw), the Your turn pill (#yourturn), Live's two options and the key hint (#keyhint), from paintAll().
function paintInputMode() {
  const ended = !!view.ended, locked = !!recorder || (busy && talkMode !== "live");
  $("modebar").hidden = ended; $("keyhint").hidden = ended;
  for (const b of $("modesw").children) {
    b.setAttribute("aria-pressed", String(b.dataset.mode === inputMode)); b.disabled = locked;
    b.title = locked ? "Finish the recording first" : "";
  }
  const yt = yourTurnState();
  $("yourturn").hidden = !yt;
  if (yt) { $("yourturn").textContent = yt.text; $("yourturn").dataset.state = yt.key; }
  $("livepills").hidden = inputMode !== "live";
  const bp = $("bargepill"), pp = $("pausepill");
  bp.textContent = "Interrupt: " + BARGE_SAYS[barge]; bp.setAttribute("aria-label", "Interrupt Claude by " + BARGE_SAYS[barge] + ". Press to change.");
  pp.textContent = "Send after " + (endPause / 1000) + " s"; pp.setAttribute("aria-label", "Send after a pause of " + (endPause / 1000) + " seconds. Press to change.");
  // A say-back question has its own placeholder (call-stage.js); otherwise the field says how it is used in this mode.
  if (!answering && $("text").placeholder !== WAIT_PLACEHOLDER) $("text").placeholder = modePlaceholder();
}
const WAIT_PLACEHOLDER = "Add to your question";
function modePlaceholder() { return inputMode === "type" ? "Type a message" : inputMode === "live" ? "Just speak, or type here" : "Type, or press the mic"; }
// The page's own layers, registered with the core: the gear (the header's and the rail's), and the Keys sheet from its two buttons.
// A layer opened or closed (the core's showPop) moves the focus into it and, when it closes, back to the button that opened it,
// unless the user already went elsewhere. The button is remembered here (popButton wraps registerPop), per layer: a layer opened
// from a row inside another (Keyboard shortcuts in the gear) hands back to the first one's button.
const openers = {};         // layer id -> the button that opened it
let lastPress = null;       // the button of ours that was pressed last
function popButton(btn, id) {
  registerPop(btn, id);
  const go = $(btn).onclick;
  $(btn).onclick = ev => { lastPress = $(btn); go(ev); };
}
popButton("gear", "pGear"); popButton("railgear", "pGear");
const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
const focusables = root => [...root.querySelectorAll(FOCUSABLE)].filter(e => !e.closest("[hidden]"));
function popChanged(now, was) {
  if (now) {
    const from = lastPress && lastPress.closest(".pop"), mine = lastPress && POPS[lastPress.id] === now ? lastPress : null;
    // A key (?) opened it: the way back is wherever the focus was, else the layer's own button.
    const kept = document.activeElement && document.activeElement !== document.body && !document.activeElement.closest(".pop") ? document.activeElement : null;
    openers[now] = (from && openers[from.id]) || mine || kept || $(Object.keys(POPS).find(b => POPS[b] === now && !$(b).closest("[hidden]")) || "gear");
    lastPress = null;
    const first = focusables($(now))[0]; if (first) first.focus();
  } else if (was) {
    const at = document.activeElement, opener = openers[was]; delete openers[was];
    if (opener && opener.isConnected && !opener.closest("[hidden]") && (!at || at === document.body || $(was).contains(at))) opener.focus();
  }
}
// Tab stays inside the layer that is open (Escape leaves it): the layer sits after the panel in the page, so without this Tab
// would walk the whole conversation first.
document.addEventListener("keydown", ev => {
  if (ev.key !== "Tab" || !openPop) return;
  const pop = $(openPop), items = focusables(pop); if (!items.length) return;
  const first = items[0], last = items[items.length - 1], at = document.activeElement;
  if (!pop.contains(at)) { ev.preventDefault(); (ev.shiftKey ? last : first).focus(); }
  else if (ev.shiftKey && at === first) { ev.preventDefault(); last.focus(); }
  else if (!ev.shiftKey && at === last) { ev.preventDefault(); first.focus(); }
});
// The voice speed, from the gear's buttons, the player's chip and the Alt+S key: one setter.
function setSpeed(s) { speed = s; store.set("speed", s); audio.playbackRate = s; paintSettings(); }
