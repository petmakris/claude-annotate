// Which voice reads the answers aloud, in the settings, in plain words: no machine, no profile, nothing an owner needs.
// Azure is quick to start and billed per character; the local engine is free and about as slow to make an answer as to say it.
function engineText() {
  if (CFG.engine === "Azure") {
    const ava = /^[a-z]{2}-[A-Z]{2}-([A-Z][a-z]+)/.exec(CFG.voice || "");
    return ((CFG.voices || []).length ? "" : (ava ? ava[1] : CFG.voice) + ", ") + t("voice.cloud");
  }
  return t("voice.local");
}
if (CFG.engine) { $("engine").textContent = engineText(); $("engine").hidden = false; }
// ---- the voice: the engine's voices to pick from, the choice kept on this origin ------------------
// The server makes each answer's audio as the answer arrives, so the choice is sent to it: when the page
// opens and whenever it changes. Answers already made keep the voice they were made in. A voice's sample
// is a few words, made once by the server and kept.
const VOICES = CFG.voices || [];
let voice = CFG.voice;
const sample = new Audio();
function relabelHear(b) { const text = t("voice.hear", {name: b.dataset.name}); b.setAttribute("aria-label", text); b.title = text; }
function paintVoices() {
  for (const b of $("voices").querySelectorAll(".vpick")) b.setAttribute("aria-checked", String(b.dataset.voice === voice));
}
function chooseVoice(id, send = true) {
  voice = id; store.set("voice", id); paintVoices();
  if (send) api("/api/voice", {method: "POST", body: JSON.stringify({voice: id}), headers: {"Content-Type": "application/json"}})
    .then(r => { if (!r.ok) showError(t("voice.failed")); }).catch(() => showError(t("voice.failed")));
}
if (VOICES.length) {
  for (const v of VOICES) {
    const row = document.createElement("div"); row.className = "vrow";
    const pick = document.createElement("button"); pick.type = "button"; pick.className = "vpick"; pick.dataset.voice = v.id;
    pick.setAttribute("role", "radio"); pick.append(v.name);
    const note = document.createElement("small"); note.textContent = v.note; pick.append(note);
    pick.onclick = () => chooseVoice(v.id);
    const hear = document.createElement("button"); hear.type = "button"; hear.className = "ib";
    hear.dataset.name = v.name; relabelHear(hear);
    hear.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z"/></svg>';
    hear.onclick = () => {
      sample.src = location.pathname.replace(/\/$/, "") + "/voice/" + encodeURIComponent(v.id);
      sample.play().catch(() => showError(t("voice.sample")));
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

// ---- the text size: Desk, or TV for reading across a room (the settings, or ?screen=tv in the address) ----
function setScreen(mode, keep = true) {
  screenMode = mode === "tv" ? "tv" : "desk"; if (keep) store.set("screen", screenMode);
  toStage({type: "stage:zoom", zoom: screenMode === "tv" ? TV_ZOOM : 1}); paintAll();
}
const screenParam = new URLSearchParams(location.search).get("screen");
if (screenParam === "tv" || screenParam === "desk") { screenMode = screenParam; store.set("screen", screenMode); }

// ---- the panel: on the left or the right, as wide as dragged ----
const PANEL_W = [300, 640];
let side = store.get("side", "right") === "left" ? "left" : "right";
let panelW = Math.min(PANEL_W[1], Math.max(PANEL_W[0], Number(store.get("panelW", 380)) || 380));
function paintPanel() {
  $("app").dataset.side = side;
  document.documentElement.style.setProperty("--pw", panelW + "px");
  for (const b of $("side").children) b.setAttribute("aria-pressed", String(b.dataset.choice === side));
}
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
  const on = (box, v) => { for (const b of $(box).children) b.setAttribute("aria-pressed", String(b.dataset.choice === String(v))); };
  for (const b of $("speeds").children) b.setAttribute("aria-pressed", String(Number(b.dataset.speed) === speed));
  for (const b of $("lang").children) b.setAttribute("aria-pressed", String(b.dataset.lang === language));
  $("autoplay").setAttribute("aria-pressed", String(autoplay));
  $("follow").setAttribute("aria-pressed", String(follow)); $("follow").disabled = !CFG.stageUrl;
  $("livemode").setAttribute("aria-pressed", String(talkMode === "live")); $("livemode").disabled = !!recorder;
  $("bargerow").hidden = $("pauserow").hidden = talkMode !== "live";
  on("barge", barge); on("endpause", endPause); on("screen", screenMode);
  $("endlbl").textContent = t(view.ended ? "set.close" : "set.end"); $("end").disabled = closed;
}
for (const s of SPEEDS) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.speed = s; b.textContent = s + "×";
  b.onclick = () => setSpeed(s);
  $("speeds").append(b);
}
$("autoplay").onclick = () => { autoplay = !autoplay; store.set("autoplay", autoplay); paintSettings(); };
$("livemode").onclick = () => setTalkMode(talkMode === "live" ? "manual" : "live");
for (const b of $("barge").children) b.onclick = () => { barge = b.dataset.choice; store.set("barge", barge); paintSettings(); };
for (const b of $("endpause").children) b.onclick = () => { endPause = Number(b.dataset.choice); store.set("endPause", endPause); paintSettings(); };
$("geardone").onclick = ev => { ev.stopPropagation(); showPop(null); };
// ---- the keys ----------------------------------------------------------------------
// Every shortcut of the page is in this list, once: the Keys sheet (#pKeys) is built from it, and test_call_input.py presses
// each row. Letters belong to the message field (a key typed anywhere lands in it), so the
// shortcuts that are not Space, the arrows or ? are Alt chords, read from the physical key (ev.code: Option types a
// character on a Mac). Every key does what a visible button does.
const KEYS = [
  {group: "g.listen", rows: [
    {id: "play", keys: ["Space"], what: "k.play"},
    {id: "sentence", keys: ["←", "→"], what: "k.sentence"},
    {id: "speed", keys: ["Alt", "S"], what: "k.speed"}]},
  {group: "g.move", rows: [
    {id: "message", keys: ["Alt", "M"], what: "k.message"},
    {id: "player", keys: ["Alt", "P"], what: "k.player"},
    {id: "voice", keys: ["Alt", "V"], what: "k.voice"},
    {id: "keys", keys: ["?"], what: "k.keys"},
    {id: "close", keys: ["Esc"], what: "k.close"}]},
  {group: "g.talk", rows: [
    {id: "send", keys: ["Enter"], what: "k.send"},
    {id: "newline", keys: ["Shift", "Enter"], what: "k.newline"},
    {id: "talk", keys: ["Alt", "T"], what: "k.talk"}]},
];
const ALT_KEYS = {KeyS: "speed", KeyM: "message", KeyP: "player", KeyV: "voice", KeyT: "talk"};
function buildKeys() {
  // `key` names the words in the table (call-i18n.js): the element keeps it in data-t, so a change of language puts the new words in
  const pop = $("pKeys"), make = (tag, cls, text, key) => { const e = document.createElement(tag); if (cls) e.className = cls; if (key) { e.dataset.t = key; e.textContent = t(key); } else if (text) e.textContent = text; return e; };
  const head = make("div", "sheethead"), close = make("button", "done", "", "set.done"); close.type = "button";
  close.onclick = ev => { ev.stopPropagation(); showPop(null); };
  head.append(make("h2", "", "", "keys.title"), close);
  const body = make("div", "sheetbody");
  for (const g of KEYS) {
    body.append(make("h3", "", "", g.group)); const sec = make("div", "group");
    for (const r of g.rows) {
      const row = make("div", "row"), keys = make("span", "kk");
      r.keys.forEach((k, i) => { if (i) keys.append(" "); keys.append(make("kbd", "", k)); });
      row.dataset.key = r.id; row.append(make("span", "kw", "", r.what), keys); sec.append(row);
    }
    body.append(sec);
  }
  body.append(make("p", "knote", "", "keys.note"));
  pop.replaceChildren(head, body);
}
buildKeys();
popButton("keysrow", "pKeys");
// Nothing is being typed: the body, an empty message field or a button of the panel has the focus.
const onModeSwitch = () => false;
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
  if (!keysFree() || (ev.key === " " && onModeSwitch())) return;   // a space on the mode switch is a typed space, not a press
  if (ev.key === " " && ev.repeat) { ev.preventDefault(); return; }
  if (mediaKey(ev.key)) ev.preventDefault();
});
// The Alt chords and ?: before the typing handler below, which skips a key already used.
document.addEventListener("keydown", ev => {
  if (ev.ctrlKey || ev.metaKey) return;
  if (ev.altKey && !ev.shiftKey && ALT_KEYS[ev.code]) { if (runShortcut(ALT_KEYS[ev.code])) ev.preventDefault(); return; }
  if (ev.key === "?" && !ev.altKey && keysFree() && !onModeSwitch()) { ev.preventDefault(); showPop("pKeys"); }
});
function runShortcut(id) {
  if (id === "speed") { cycleSpeed(); return true; }
  if (id === "message") { $("text").focus(); return true; }
  if (id === "player") { const b = $("playpause"); if (!b || b.closest("[hidden]")) return false; b.focus(); return true; }
  if (id === "voice") { if (!CFG.stageUrl) return false; followAgain(); return true; }
  if (id === "talk") { talkPress(); return true; }
  return false;
}
// The skip links, the first stops of the page: past the stage and every answer, to the message, to the player or to the board in front.
for (const [id, to] of [["skipmsg", "message"], ["skipplay", "player"]]) {
  $(id).onclick = ev => { ev.preventDefault(); runShortcut(to); };
}
// The position slider's arrows are sentence steps, as the left and right keys are; Page Up and Page Down ten seconds.
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
const LANG_NAMES = {auto: null, en: "English", el: "Ελληνικά"};   // Detect is said in the page's language (lang.auto)
for (const code of CFG.languages) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.lang = code;
  if (code === "auto") { b.dataset.t = "lang.auto"; b.textContent = t("lang.auto"); } else b.textContent = LANG_NAMES[code] || code.toUpperCase();
  b.onclick = () => { language = code; store.set("language", code); paintAll(); };
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
  showError(""); showMicNote("");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { showError(t("mic.unavailable")); return; }
  let stream;
  starting = true;
  try { stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true}}); }
  catch (err) { showError(t("mic.none", {why: err.message})); return; }
  finally { starting = false; }
  if (recorder) { stream.getTracks().forEach(track => track.stop()); return; }
  takeFloor(null);
  audio.pause();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const source = ctx.createMediaStreamSource(stream);
  const node = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  node.onaudioprocess = ev => {
    const d = ev.inputBuffer.getChannelData(0); chunks.push(new Float32Array(d));
    let peak = 0; for (let i = 0; i < d.length; i += 16) peak = Math.max(peak, Math.abs(d[i]));
    if (recorder) recorder.peak = Math.max(recorder.peak, peak);
    levels.push(Math.min(1, peak * 1.6)); levels.shift();
    if (!meterRaf) meterRaf = requestAnimationFrame(paintMeter);
  };
  source.connect(node); node.connect(ctx.destination);
  const started = Date.now();
  const timer = setInterval(() => $("rectime").textContent = fmt((Date.now() - started) / 1000), 250);
  recorder = {stream, ctx, source, node, chunks, timer, peak: 0};
  $("rectime").textContent = "0:00"; setMode("recording");
}

function stopRecording() {
  const r = recorder; recorder = null;
  clearInterval(r.timer); r.node.disconnect(); r.source.disconnect();
  r.stream.getTracks().forEach(track => track.stop()); r.ctx.close();
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
  const wav = toWav(r.chunks, r.ctx.sampleRate);
  wav.heard = {seconds: r.chunks.reduce((n, c) => n + c.length, 0) / r.ctx.sampleRate, peak: r.peak || 0};  // kept with the recording, for the note when it comes back empty
  await sendWav(wav);
}
// "Nothing was heard", said where the mic is: above the field, with how long the recording was and whether the microphone gave
// any signal at all (a peak near zero is a muted or dead microphone, anything else a voice too far away), until the next press.
const NEAR_ZERO_PEAK = 0.01;
function micNoteText(heard) {
  const how = heard && heard.seconds >= 0.5 ? t("heard.how", {s: heard.seconds < 10 ? heard.seconds.toFixed(1) : Math.round(heard.seconds)}) : "";
  return t(heard && heard.peak < NEAR_ZERO_PEAK ? "heard.dead" : "heard.faint", {how});
}

// A recording comes back as words in the text field, to be checked and changed before Send; nothing
// reaches Claude until then. While the server restarts (503, or no answer at all) the recording is sent
// again until the next server takes it, for up to three minutes. One still not taken is kept for Send again.
async function sendWav(wav) {
  unsent = null; showMicNote("");
  setMode("busy");
  const until = Date.now() + 180000;
  for (let wait = 1000; ; wait = Math.min(wait * 2, 8000)) {
    let resp = null, failed = "";
    try { resp = await api("/api/listen?draft=1&lang=" + language, {method: "POST", body: wav, headers: {"Content-Type": "audio/wav"}}); }
    catch (err) { failed = err.message; }
    if (resp && resp.status !== 503) {
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) { if (![410, 413].includes(resp.status)) unsent = wav; showError(body.error || t("send.http", {code: resp.status})); }
      else if (!body.text) showMicNote(micNoteText(wav.heard));
      else writeOut(body.text);
      break;
    }
    if (Date.now() > until) { unsent = wav; showError(t("send.failed", {why: failed || t("send.restarting")})); break; }
    errText = t("send.reconnect"); paintToast();
    await new Promise(ok => setTimeout(ok, wait));
  }
  if (errText === t("send.reconnect")) showError("");
  setMode("idle");
}

// Typing is as direct as talking: a key pressed anywhere on the page goes to the text field.
document.addEventListener("keydown", ev => {
  if (ev.defaultPrevented || ev.ctrlKey || ev.metaKey || ev.altKey || ev.key.length !== 1 || openPop || recorder || view.ended) return;
  if (document.activeElement && document.activeElement !== document.body && !onModeSwitch()) return;
  $("text").focus();
});

for (const b of $("screen").children) b.onclick = () => setScreen(b.dataset.choice);
function setTalkMode(mode) {
  talkMode = mode; store.set("talkMode", mode);
  if (mode === "live") { if (recorder) sendRecording(); startLive(); }   // an open recording goes first, once
  else stopLive();
  paintAll();
}

// A turn that is only "slower", "faster" or "say that again slower" is a command to the player, not a question for Claude: typed (or
// said with Talk and written out) it is acted on here by the same code as Live's spoken commands and never sent. The words are the
// ones talk.py's COMMANDS holds for these commands (test_call_input.py keeps the two lists together); anything more than the command,
// and "please" or "Claude" aside, is an ordinary turn.
const LOCAL_COMMANDS = {"slower": "slower", "go slower": "slower", "slow down": "slower", "speak slower": "slower", "talk slower": "slower",
  "faster": "faster", "go faster": "faster", "speed up": "faster", "speak faster": "faster", "talk faster": "faster",
  "say that again slower": "repeat_slower", "repeat that slower": "repeat_slower", "repeat slower": "repeat_slower",
  "repeat": "repeat", "repeat that": "repeat", "say that again": "repeat", "come again": "repeat",
  "πιο αργά": "slower", "πιο γρήγορα": "faster", "ξαναπές το πιο αργά": "repeat_slower", "ξαναπές το": "repeat", "πάλι": "repeat"};
const COURTESY_WORDS = new Set(["please", "claude", "ok", "okay", "now", "παρακαλώ"]);
function localCommand(text) {
  const words = String(text || "").toLowerCase().match(/[\p{L}\p{N}_]+/gu) || [];
  while (words.length && COURTESY_WORDS.has(words[0])) words.shift();
  while (words.length && COURTESY_WORDS.has(words[words.length - 1])) words.pop();
  return LOCAL_COMMANDS[words.join(" ")] || null;
}
// The send path asks first: true when the text was a command (applied, the field cleared), so nothing goes to Claude.
function typedCommand(text) {
  const cmd = localCommand(text);
  if (!cmd || view.ended) return false;
  $("text").value = ""; spoken = false; fitText();
  const before = liveFlash;
  runCommand(cmd, {});
  // Every command says it was taken: a repeat with nothing to repeat would otherwise clear the field and show nothing.
  if (liveFlash === before) flash(t(cmd.startsWith("repeat") ? (current || (lastAnswer() || {}).speech === "ready" ? "cmd.repeat" : "cmd.nothing") : "cmd.done"));
  if (liveFlash && Date.now() < liveFlash.until) announce(liveFlash.text);
  paintAll();   // the flash in the foot, the Your turn pill with the field empty
  return true;
}
// The voice speed, one press to the next: the player's chip and Alt+S.
function cycleSpeed() { setSpeed(SPEEDS[(SPEEDS.indexOf(speed) + 1) % SPEEDS.length]); announce(t("speed.say", {x: speed})); }

// In live mode the mic button mutes and unmutes the open microphone (the stream, the floor and this page's claim stay); while
// Chrome holds the audio back it starts it, and the same press must not then mute. Leaving Live is the switch.
function liveButton() {
  if (live && (live.suspended || performance.now() - wokeAt < 1000)) { wakeLive(); return; }
  if (live && live.parked) { claimLive(); return; }
  if (live) setMuted(!live.muted); else startLive();
}
// What the mic button does: the page's one Talk press, for the button and Alt+T.
function talkPress() {
  if (busy && talkMode !== "live") return;
  if (talkMode === "live") liveButton(); else if (recorder) sendRecording(); else startRecording();
}
$("talk").onclick = talkPress;
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
    if (!r.ok) throw new Error(b.error || t("http", {code: r.status}));
    if (tab) tab.location = b.path; else location.assign(b.path);
  } catch (err) { if (tab) tab.close(); showError(t("demo.failed", {why: err.message})); }
  showPop(null);
};
$("end").onclick = () => {
  if (!view.ended) { api("/api/stop", {method: "POST"}).then(() => { view.v = -1; if (wake) wake(); }); return; }
  api("/api/close", {method: "POST"}).finally(() => { closed = true; paintAll(); });
};

// ---- the hooks this file owns (I) -----------------------------------------------
// The mic and the field, from paintPill(): the mic sits in the field until words are typed, then Send takes its place, as in
// a phone's messages. While recording the field gives way to the level and the time, with Cancel and Done. In Live the mic
// mutes and unmutes the open microphone, and stays beside Send.
function paintMic() {
  const rec = !!recorder, ended = !!view.ended, liveMode = talkMode === "live", typed = !!$("text").value.trim();
  const liveLabel = t(!live ? "mic.listen" : live.suspended ? "mic.start" : live.parked ? "mic.here" : live.muted ? "mic.unmute" : "mic.mute");
  const label = liveMode ? liveLabel : t("foot.talk");
  const b = $("talk");
  b.hidden = ended || rec || (typed && !liveMode); b.disabled = busy && !liveMode; b.classList.toggle("busy", busy && !liveMode);
  if (b.getAttribute("aria-label") !== label) { b.setAttribute("aria-label", label); b.title = label + (liveMode ? "" : " · Alt+T"); }
  b.classList.toggle("live", liveMode); b.classList.toggle("muted", liveMode && !listening());
  $("cancel").hidden = !rec; $("send").hidden = !rec;
  $("text").hidden = rec || ended; $("sendtext").hidden = rec || ended || !typed; $("pill").hidden = ended && !rec;
  $("wave").hidden = !rec;
  if (!answering && !rec) { const ph = t(waitActive() ? "ph.wait" : liveMode ? "ph.live" : "ph.talk"); if ($("text").placeholder !== ph) $("text").placeholder = ph; }
  if (ended) clearDraft();
}
// The page's own layers, registered with the core: the gear, and the Keys sheet from its row in the gear and the ? key.
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
popButton("gear", "pGear");
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
// A change of language (call-i18n.js applyLang): the words this file made itself are said again.
function relabelPage() {
  if (CFG.engine) $("engine").textContent = engineText();
  for (const b of $("voices").querySelectorAll(".ib")) relabelHear(b);
  relabelShell();
}
// The voice speed, from the gear's buttons, the player's chip and the Alt+S key: one setter.
function setSpeed(s) { speed = s; store.set("speed", s); audio.playbackRate = s; paintSettings(); }
