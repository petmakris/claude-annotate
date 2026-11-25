// Which engine reads the answers aloud, in the settings: Azure is fast and billed, VoiceStudio is local and slow.
if (CFG.engine) {
  const ava = /^[a-z]{2}-[A-Z]{2}-([A-Z][a-z]+)/.exec(CFG.voice || "");
  $("engine").textContent = CFG.engine === "Azure" ? "Azure" + ((CFG.voices || []).length ? "" : " · " + (ava ? ava[1] : CFG.voice)) + ": fast, billed per character"
    : "VoiceStudio on this Mac, profile " + CFG.voice + ": free, slower";
  $("engine").hidden = false;
}
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
for (const s of SPEEDS) {
  const b = document.createElement("button"); b.type = "button"; b.dataset.speed = s; b.textContent = s + "×";
  b.onclick = () => setSpeed(s);
  $("speeds").append(b);
}
$("autoplay").onclick = () => { autoplay = !autoplay; store.set("autoplay", autoplay); paintSettings(); };
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
  ms.setActionHandler("play", () => { readerPlays(current); audio.play(); }); ms.setActionHandler("pause", () => audio.pause());
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
// recording, the text field, the Send button.
function paintMic() {
  const rec = !!recorder, ended = !!view.ended;
  const liveMode = talkMode === "live";
  const liveLabel = !live ? "Listen" : live.suspended ? "Start listening" : live.parked ? "Listen here" : "Stop listening";
  const talkLabel = rec ? "Done" : liveMode ? liveLabel : "Talk";
  // The rail's mic is the panel's: the same label, the same look.
  for (const id of ["talk", "railtalk"]) {
    const b = $(id);
    b.hidden = ended; b.disabled = busy && !liveMode; b.classList.toggle("busy", busy && !liveMode);
    b.setAttribute("aria-label", talkLabel); b.dataset.tip = talkLabel;
    b.classList.toggle("live", liveMode); b.classList.toggle("muted", liveMode && !listening());
  }
  $("cancel").hidden = !rec; $("send").hidden = !rec;
  $("text").hidden = rec || ended; $("sendtext").hidden = rec || ended; $("pill").hidden = ended && !rec;
}
// The mode, always on screen: from across the room the mic button alone does not say it.
function paintModeChip() {
  $("modechip").textContent = talkMode === "manual" ? "Press to talk" : listening() ? "Live · listening" : "Live · off";
  $("modechip").classList.toggle("on", listening());
}
// The Type / Talk / Live switch (#modesw), the Your turn pill (#yourturn) and the key hint (#keyhint), from paintAll().
function paintInputMode() {}
// The page's own popovers, registered with the core: the gear and, when built, the Keys sheet (#pKeys, from #keysbtn).
registerPop("gear", "pGear"); registerPop("railgear", "pGear");
// A layer opened or closed (the core's showPop): `now` is the id of the popover open now or null, `was` the one open before.
// Where focus moves into a sheet and comes back to its button.
function popChanged(now, was) {}
// The voice speed, from the gear's buttons and from the Now card's speed chip (C): one setter.
function setSpeed(s) { speed = s; store.set("speed", s); audio.playbackRate = s; paintSettings(); }
